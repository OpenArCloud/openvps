"""
Live cache of discovery Announces seen on the bus.

The bridge answers `/.well-known/spatialdds/search` from this cache in one
round trip, rather than issuing a CoverageQuery per request. That makes the
cache's freshness the endpoint's correctness: a service that departed or whose
announce expired must not appear in results.

Removal paths, and one limitation worth stating plainly:

  * **Depart** — a `DEPART` message for a service_id evicts it.
  * **TTL expiry** — an entry older than ``ttl_sec × TTL_MULTIPLIER`` is swept.
    Swept lazily on read, which is sufficient at demo scale.
  * **DDS dispose** — the primary signal, now that announces are typed.
    ``spatial::disco::Announce`` is keyed on ``service_id``, so disposing an
    instance means "this service is gone" and the cache evicts exactly it.
    This is what the unkeyed envelope could not express: every announce was a
    sample on one instance, so NOT_ALIVE_DISPOSED referred to the topic.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from spatialdds_demo.discovery_http import ServiceRecord, record_from_announce
from spatialdds_demo.json_mapping import to_json

# Spec backstop: consumers should not use an announce beyond stamp + ttl_sec.
# Doubling it tolerates modest clock skew between publisher and gateway, and
# matches the freshness rule the demo client already applies.
TTL_MULTIPLIER = 2.0


def _stamp_seconds(payload: Dict[str, Any]) -> Optional[float]:
    stamp = payload.get("stamp")
    if not isinstance(stamp, dict):
        return None
    try:
        return float(stamp.get("sec", 0)) + float(stamp.get("nanosec", 0)) / 1e9
    except (TypeError, ValueError):
        return None


class AnnounceCache:
    """Thread-safe, latest-wins-by-service_id cache of announces."""

    def __init__(self, ttl_multiplier: float = TTL_MULTIPLIER):
        self._entries: Dict[str, ServiceRecord] = {}
        self._ttl_multiplier = ttl_multiplier
        self._lock = threading.Lock()
        self.admitted = 0
        self.departed = 0
        self.expired = 0

    # -- ingestion ---------------------------------------------------------
    def admit(self, announce: Dict[str, Any]) -> bool:
        """
        Cache an announce, latest wins. Returns False if it is unusable.

        A malformed announce is dropped rather than raising: the bus is not a
        trusted caller, and one bad publisher must not take the endpoint down.
        """
        try:
            record = record_from_announce(dict(announce))
        except Exception:
            return False
        if not record.service_id:
            return False
        with self._lock:
            self._entries[record.service_id] = record
            self.admitted += 1
        return True

    def admit_typed(self, announce) -> bool:
        """
        Cache a typed ``Announce`` straight off the bus.

        Flattened to JSON at this boundary so everything above the cache — the
        shared discovery core and the HTTP responses — is unchanged by the move
        to typed topics.
        """
        try:
            return self.admit(to_json(announce))
        except Exception:
            return False

    def apply_events(self, events) -> int:
        """
        Fold a batch of AnnounceEvents in: admit the living, evict the departed.

        Returns how many entries changed.
        """
        changed = 0
        for event in events:
            if event.alive and event.announce is not None:
                if self.admit_typed(event.announce):
                    changed += 1
            elif event.service_id and self.depart(event.service_id):
                changed += 1
        return changed

    def depart(self, service_id: str) -> bool:
        """Evict a service that announced its departure. True if it was cached."""
        if not service_id:
            return False
        with self._lock:
            removed = self._entries.pop(service_id, None) is not None
            if removed:
                self.departed += 1
        return removed

    # -- reads -------------------------------------------------------------
    def records(self, now: Optional[float] = None) -> List[ServiceRecord]:
        """Live records, sweeping anything past its TTL backstop first."""
        self.sweep(now)
        with self._lock:
            return list(self._entries.values())

    def sweep(self, now: Optional[float] = None) -> int:
        """Drop expired entries. Returns how many went."""
        now = time.time() if now is None else now
        dropped = 0
        with self._lock:
            for service_id, record in list(self._entries.items()):
                if self._is_expired(record, now):
                    del self._entries[service_id]
                    dropped += 1
            self.expired += dropped
        return dropped

    def _is_expired(self, record: ServiceRecord, now: float) -> bool:
        ttl = record.payload.get("ttl_sec")
        stamp = _stamp_seconds(record.payload)
        if not ttl or stamp is None:
            # No TTL or no stamp: nothing to expire against, so keep it. Depart
            # remains the removal path.
            return False
        try:
            budget = float(ttl) * self._ttl_multiplier
        except (TypeError, ValueError):
            return False
        return (now - stamp) > budget

    def get(self, service_id: str) -> Optional[ServiceRecord]:
        with self._lock:
            return self._entries.get(service_id)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "cached": len(self._entries),
                "admitted": self.admitted,
                "departed": self.departed,
                "expired": self.expired,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
