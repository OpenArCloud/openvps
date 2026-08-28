# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
"""
Lifecycle: the DDS participant, the poll thread, and the one worker both surfaces share.

Off by default. `OPENVPS_DDS_ENABLED` turns it on, so a deployment that does not want a DDS
participant gets exactly the behaviour it had before, and the HTTP path is untouched whether
this runs or not.

**One worker, shared.** The GPU serialises regardless, and the HTTP handler already occupies
it. Giving the DDS reader its own thread and letting both call the localizer directly would
turn an implicit queue into a real race over the localizer's per-call state. Both paths
therefore hand work to the same single-threaded executor. This does not fix the pre-existing
problem of the HTTP handler making a blocking GPU call on the event loop — that is upstream's
to decide — but it stops this branch from making it worse.

**The heartbeat.** The deployment's idle detector stops a host that looks unused, and a DDS
client is invisible to every check it makes: RTPS is UDP so it is not an established TCP
connection, it writes no HTTP access log, and at the 0.1-1 Hz a VPS is queried at the GPU
check samples an instant between requests. Touching a file on each served request is the only
signal it can see. Without it the host shuts down under an actively connected client.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("openvps.spatialdds")


def enabled() -> bool:
    return os.environ.get("OPENVPS_DDS_ENABLED", "").strip().lower() in ("1", "true", "yes")


def domain_id() -> int:
    return int(os.environ.get("SPATIALDDS_DDS_DOMAIN", "0"))


class Heartbeat:
    """Touches a file when the DDS path serves a request. See the module docstring."""

    def __init__(self, path: Optional[str] = None):
        raw = path if path is not None else os.environ.get("OPENVPS_DDS_HEARTBEAT", "")
        self.path = Path(raw) if raw else None
        self._last = 0.0

    def beat(self, min_interval_s: float = 5.0) -> None:
        if self.path is None:
            return
        now = time.time()
        if now - self._last < min_interval_s:
            return          # the idle window is minutes; one touch per request is wasteful
        self._last = now
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch()
        except OSError as exc:
            # Never fail a localization because the heartbeat could not be written. A host
            # that may shut down early is recoverable; a dropped fix is not.
            log.warning("could not write DDS heartbeat %s: %s", self.path, exc)


class SharedWorker:
    """
    The single thread both surfaces queue through.

    ``submit`` returns a Future so the DDS poll loop does not block on the GPU while other
    requests are arriving — chunks keep being taken and reassembled while a localization
    runs, which is what keeps a slow query from stalling the ones behind it.
    """

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openvps-localize")

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        return self._pool.submit(fn, *args, **kwargs)

    def run(self, fn: Callable, *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs).result()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


class DdsRuntime:
    """Owns the poll thread; started and stopped from the app lifespan."""

    def __init__(self, service, announcer=None, poll_interval_s: float = 0.05):
        self._service = service
        self._announcer = announcer
        self._interval = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="openvps-dds", daemon=True)
        self._thread.start()
        log.info("DDS participant serving on domain %d", domain_id())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._service.poll()
                if self._announcer is not None:
                    self._announcer.tick()
            except Exception:
                # A poll that raises must not kill the thread: the service would go silent
                # while the process stayed healthy, which is the worst of both.
                log.exception("DDS poll failed; continuing")
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._announcer is not None:
            try:
                self._announcer.depart()
            except Exception:
                log.exception("failed to dispose announce on shutdown")
