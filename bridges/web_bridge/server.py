#!/usr/bin/env python3
"""SpatialDDS HTTP/WebSocket bridge.

Two generations of endpoints live in this server:

  Legacy (kept for the Cesium web demo)
  ─────────────────────────────────────
    GET  /health                   — service announcement + DDS domain
    POST /v1/localize              — Phase 3 localize one-shot
    POST /v1/catalog/query         — Phase 4 catalog one-shot
    WS   /v1/stream                — every received envelope, no filtering

  Generic protocol (new, for arbitrary browser consumers)
  ────────────────────────────────────────────────────────
    WS   /ws                       — subscribe/publish/list_topics/ping
    GET  /api/topics               — REST topic discovery
    GET  /api/stats                — bridge-level counters

The generic side reuses the existing DDS transport: each envelope received
on the bus is fanned out to BOTH the legacy broadcaster (raw, all clients)
and the new ClientManager (per-client topic-pattern + msg_type filtering,
optional rate limiting). Browser-to-DDS publishing resolves the requested
msg_type through the 3.3.2 registry and writes a real typed sample.
"""

import json
import os
import queue
import sys
import threading
import time
import uuid
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from spatialdds_demo.dds_transport import require_dds_env
from spatialdds_demo.discovery_bus import AnnounceSubscriber
from spatialdds_demo.discovery_http import (
    normalize_search_request,
    record_from_announce,
    DiscoveryError,
    bootstrap_manifest,
    search as discovery_search,
)
from spatialdds_demo.json_mapping import from_json, to_json
from spatialdds_demo.service_bus import CatalogClient, CoverageClient, VpsClient
from spatialdds_idl.oarc_demo import CatalogQuery as TypedCatalogQuery
from spatialdds_idl.spatial.argeo import VpsRequest as TypedVpsRequest
from spatialdds_idl.spatial.disco import CoverageQuery as TypedCoverageQuery
from spatialdds_demo.manifest_resolver import resolve_manifest
from spatialdds_demo.topics import (
    TOPIC_CATALOG_QUERY_V1,
    TOPIC_CATALOG_REPLIES,
    TOPIC_DISCOVERY_QUERY_V1,
    TOPIC_VPS_QUERY_V1,
)
from spatialdds_validation import SpatialDDSValidator, create_coverage_bbox_earth_fixed
from spatialdds_test import MockSensorData

# Sibling modules (topic router + client manager)
_HERE = Path(__file__).resolve().parent
_BRIDGES = _HERE.parent
for p in (str(_HERE), str(_BRIDGES)):
    if p not in sys.path:
        sys.path.insert(0, p)
from topic_router import TopicRouter  # noqa: E402
from client_manager import ClientManager  # noqa: E402
from announce_cache import AnnounceCache  # noqa: E402

DEFAULT_LAT = float(os.getenv("SPATIALDDS_BRIDGE_DEFAULT_LAT", "30.284996"))
DEFAULT_LON = float(os.getenv("SPATIALDDS_BRIDGE_DEFAULT_LON", "-97.739494"))
DEFAULT_ALT = float(os.getenv("SPATIALDDS_BRIDGE_DEFAULT_ALT", "18"))
ANNOUNCE_TTL_SEC = int(os.getenv("SPATIALDDS_BRIDGE_ANNOUNCE_TTL", "300"))
# Demo-local catalog filter default (the catalog protocol is not a spec
# surface). Replaces the old expr string now that CoverageQuery.expr is gone.
DEFAULT_CATALOG_KINDS = ["overlay", "poi", "mesh"]


class SpatialDDSBridge:
    def __init__(self) -> None:
        self._domain_id: Optional[int] = None
        self._last_announce: Optional[Dict[str, Any]] = None
        self._announce_sub: Optional[AnnounceSubscriber] = None
        self._announce_participant = None
        self._coverage = None
        self._vps: Optional[VpsClient] = None
        self._catalog: Optional[CatalogClient] = None
        self._announces = AnnounceCache()
        self._client_frame_ref = SpatialDDSValidator.create_frame_ref("client/handset")
        self._stream_ref = SpatialDDSValidator.create_frame_ref("rig/front_cam")
        self._frame_seq = 1
        self._request_lock = queue.Queue(maxsize=1)
        self._request_lock.put(True)
    def ensure_transport(self) -> int:
        if self._domain_id is not None:
            return self._domain_id
        domain_id = _env_domain_id()
        if domain_id is None:
            raise RuntimeError("SPATIALDDS_DDS_DOMAIN is required")
        self._domain_id = domain_id
        self._start_transport(domain_id)
        return domain_id

    def _start_transport(self, domain_id: int) -> None:
        # One participant for everything this bridge reads and writes:
        # announces, the VPS and catalogue request/reply pairs, and the
        # streaming fanout. The envelope transport that used to sit here
        # existed to correlate replies; VpsClient and CatalogClient do that
        # on their own typed topics now, correlating on the request_id and
        # query_id the reply mirrors rather than on an envelope field.
        from cyclonedds.domain import DomainParticipant
        self._announce_participant = DomainParticipant(domain_id)
        self._announce_sub = AnnounceSubscriber(self._announce_participant)

    def _announce_fresh(self, announce: Dict[str, Any]) -> bool:
        ttl_sec = announce.get("ttl_sec")
        stamp = announce.get("stamp")
        if not ttl_sec or not stamp:
            return True
        try:
            stamp_time = float(stamp.get("sec", 0)) + float(stamp.get("nanosec", 0)) / 1_000_000_000.0
        except (TypeError, ValueError):
            return True
        return (time.time() - stamp_time) <= float(ttl_sec) * 2.0

    def drain_announces(self) -> int:
        """
        Pull whatever the announce reader has and fold it into the cache.

        Called before every read so the cache reflects the bus at answer time.
        Returns how many samples were admitted.
        """
        if not self._announce_sub:
            self.ensure_transport()
        if not self._announce_sub:
            return 0
        events = self._announce_sub.poll()
        changed = self._announces.apply_events(events)
        for event in events:
            if event.alive and event.announce is not None:
                self._last_announce = to_json(event.announce)
        return changed

    def announce_records(self):
        """Live, unexpired announce records for the discovery endpoints."""
        self.drain_announces()
        return self._announces.records()

    def coverage_records(self, coverage, coverage_frame_ref, window: float = 1.5):
        """
        Discover services by asking the bus, not by reading the cache.

        Issues a real `spatial::disco::CoverageQuery` on the well-known topic
        and gathers the `CoverageResponse` each service sends back. That is the
        DDS half of discovery actually happening — visible on the stream,
        answered by the services themselves — rather than the bridge deciding
        privately from announces it happens to hold.

        The returned `ServiceSummary` rows are deliberately compact (§3.3), so
        they name *which* services matched but cannot describe them. Their
        detail comes from the retained announce this bridge already holds,
        which is exactly what §3.3 says to do: resolve the summary to the
        manifest the HTTP binding would have returned.

        Returns None when the bus answers nothing, so the caller can fall back
        to the cache rather than reporting an empty deployment.
        """
        self.ensure_transport()
        if self._coverage is None:
            client_id = f"bridge-{uuid.uuid4().hex[:6]}"
            self._coverage = CoverageClient(
                self._announce_participant,
                f"spatialdds/discovery/replies/{client_id}/v1")
        now = SpatialDDSValidator.now_time()
        query = {
            "query_id": str(uuid.uuid4()),
            "coverage": coverage,
            "coverage_frame_ref": coverage_frame_ref,
            # No transform evaluation instant: the demo's coverage is static,
            # so there is nothing to evaluate "as of".
            "has_coverage_eval_time": False,
            "coverage_eval_time": now,
            # The HTTP binding's own `filter` is applied by the shared core
            # against the returned records, so the bus query stays broad and
            # the two cannot disagree about what a filter means.
            "has_filter": False,
            "filter": {"type_in": [], "qos_profile_in": [], "module_id_in": []},
            "reply_topic": self._coverage.reply_topic,
            "stamp": now,
            "ttl_sec": 30,
        }
        responses = self._coverage.gather(
            from_json(TypedCoverageQuery, query), window=window)

        # Relay the exchange. Nothing announces the well-known discovery topic
        # and the reply topic is client-chosen, so the announce-driven relay
        # cannot see either — yet both are real samples: the query was written
        # to the bus (the services log receiving it) and each response was read
        # off it. Emitted after the fact, under the registered type names, so
        # this is a record of what happened rather than a statement of intent.
        _emit_dds_event({
            "ts": time.time(), "dir": "tx", "domain": self._domain_id,
            "msg_type": "coverage_query",
            "logical_topic": TOPIC_DISCOVERY_QUERY_V1,
            "request_id": query["query_id"], "payload": query,
        })
        for response in responses:
            _emit_dds_event({
                "ts": time.time(), "dir": "rx", "domain": self._domain_id,
                "msg_type": "coverage_response",
                "logical_topic": self._coverage.reply_topic,
                "request_id": query["query_id"], "payload": to_json(response),
            })

        summaries = {
            summary.service_id: summary
            for response in responses
            for summary in (response.results or [])
        }
        if not summaries:
            return None

        # Detail comes from the retained announce where we hold one — it has
        # the topics and caps a ServiceSummary deliberately omits. Where we do
        # not, the summary itself still answers the question that was asked:
        # who covers this area. Falling back to the cache *per service* rather
        # than wholesale matters, because a service can be answering queries
        # while its announce has lapsed from the cache, and dropping it then
        # would report "nobody covers you" about a service that just said it
        # does.
        by_id = {r.service_id: r for r in self.announce_records()}
        records = []
        for service_id in sorted(summaries):
            record = by_id.get(service_id)
            if record is None:
                record = record_from_announce(
                    to_json(summaries[service_id]), validate=False)
            records.append(record)
        return records

    def announce_stats(self) -> Dict[str, int]:
        self.drain_announces()
        return self._announces.stats()

    def latest_announce(self, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        if self._last_announce and self._announce_fresh(self._last_announce):
            return self._last_announce
        if not self._announce_sub:
            self.ensure_transport()
        if not self._announce_sub:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            # Same drain the discovery endpoints use, so every announce the
            # bridge sees lands in the cache no matter who asked first.
            if self.drain_announces() and self._last_announce:
                if self._announce_fresh(self._last_announce):
                    return self._last_announce
            time.sleep(0.05)
        return self._last_announce

    def localize(
        self,
        prior_geopose: Optional[Dict[str, Any]] = None,
        service_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        _lock(self._request_lock)
        try:
            self.ensure_transport()
            if not service_id:
                announce = self.latest_announce(timeout=6.0)
                if not announce:
                    raise RuntimeError("No ANNOUNCE received")
                service_id = announce.get("service_id", "")
            request = self._create_localize_request(service_id, prior_geopose)
            if self._vps is None:
                self._vps = VpsClient(self._announce_participant)
            typed = self._vps.request(from_json(TypedVpsRequest, request), timeout=8)
            if typed is None:
                raise RuntimeError("LOCALIZE_RESPONSE timeout")
            return to_json(typed)
        finally:
            _unlock(self._request_lock)

    def catalog_query(
        self,
        geopose: Dict[str, Any],
        kind_in: Optional[List[str]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        _lock(self._request_lock)
        try:
            self.ensure_transport()
            if self._catalog is None:
                client_id = f"bridge-{uuid.uuid4().hex[:6]}"
                self._catalog = CatalogClient(
                    self._announce_participant, TOPIC_CATALOG_REPLIES(client_id))
            reply_topic = self._catalog.reply_topic
            query = self._create_catalog_query(
                geopose, reply_topic, limit=limit, kind_in=kind_in
            )

            typed = self._catalog.query(from_json(TypedCatalogQuery, query), timeout=6)
            if typed is None:
                raise RuntimeError("CATALOG_RESPONSE timeout")
            response = to_json(typed)
            # Relay the reply, because it really did land on the bus and this
            # participant really did read it — the announce-driven relay
            # cannot, since a CatalogQuery names a client-chosen reply topic
            # that by definition is never announced. Without this the
            # catalogue half of the demo is invisible on the stream while the
            # VPS half is not, purely because the VPS reply topic happens to
            # be announced.
            _emit_dds_event(
                {
                    "ts": time.time(),
                    "dir": "rx",
                    "domain": self._domain_id,
                    "msg_type": "oarc.catalog_response",
                    "logical_topic": reply_topic,
                    "request_id": response.get("query_id", ""),
                    "payload": response,
                }
            )
            return response
        finally:
            _unlock(self._request_lock)

    def _create_localize_request(
        self, service_id: str, prior_geopose: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        query_id = str(uuid.uuid4())
        prior = prior_geopose or _default_prior_geopose()
        # Query imagery by reference (argeo::VpsRequest.query_blobs), never
        # inline bytes; the bytes travel out-of-band as BlobChunk (§3.2).
        payload = f"MOCK_IMAGE_{self._frame_seq}".encode("utf-8")
        query_image = MockSensorData.blob_ref("vps/query-image", payload)
        request = {
            "query_id": query_id,
            "service_id": service_id,
            "client_frame_ref": self._client_frame_ref,
            "has_prior_geopose": True,
            "prior_geopose": prior,
            "query_blobs": [query_image],
            "query_stream_id": self._stream_ref["fqn"],
            "has_quality_requirements": True,
            "quality_requirements": {"max_rmse_m": 0.2, "min_confidence": 0.6},
            "stamp": SpatialDDSValidator.now_time(),
        }
        self._frame_seq += 1
        return request

    def _vision_frame(self) -> Dict[str, Any]:
        stamp = SpatialDDSValidator.now_time()
        payload = f"MOCK_IMAGE_{self._frame_seq}".encode("utf-8")
        blob = MockSensorData.blob_ref("image/jpeg", payload)
        hdr = {
            "stream_id": self._stream_ref["fqn"],
            "frame_seq": self._frame_seq,
            "t_start": stamp,
            "t_end": stamp,
            "has_sensor_pose": True,
            "sensor_pose": {"t": [0.0, 0.0, 0.0], "q": [0.0, 0.0, 0.0, 1.0]},
            "blobs": [blob],
        }
        return {
            "stream_id": self._stream_ref["fqn"],
            "frame_seq": self._frame_seq,
            "hdr": hdr,
            "codec": "JPEG",
            "pix": "RGB8",
            "color": "SRGB",
            "has_line_readout_us": False,
            "line_readout_us": 0.0,
            "rectified": True,
            "is_key_frame": True,
            "quality": {
                "has_snr_db": True,
                "snr_db": 28.0,
                "percent_valid": 99.0,
                "health": "OK",
                "note": "synthetic frame",
            },
        }

    def _create_catalog_query(
        self,
        geopose: Dict[str, Any],
        reply_topic: str,
        limit: int = 20,
        page_token: str = "",
        kind_in: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Build a demo-local catalog query.

        The catalog protocol is demo-specific, not a spec surface, but it used
        to carry an `expr` string mirroring the (now deleted)
        CoverageQuery.expr. It now carries a structured filter in the same
        has_filter + `*_in` style discovery uses.
        """
        query_id = str(uuid.uuid4())
        padding = 0.005
        coverage_frame_ref, coverage_elem = create_coverage_bbox_earth_fixed(
            geopose.get("lon_deg", DEFAULT_LON) - padding,
            geopose.get("lat_deg", DEFAULT_LAT) - padding,
            geopose.get("lon_deg", DEFAULT_LON) + padding,
            geopose.get("lat_deg", DEFAULT_LAT) + padding,
        )
        kinds = list(kind_in if kind_in is not None else DEFAULT_CATALOG_KINDS)
        return {
            "query_id": query_id,
            "reply_topic": reply_topic,
            "coverage": [coverage_elem],
            "coverage_frame_ref": coverage_frame_ref,
            "has_coverage_eval_time": False,
            "has_filter": bool(kinds),
            "filter": {"kind_in": kinds},
            "limit": limit,
            "page_token": page_token,
            "stamp": SpatialDDSValidator.now_time(),
            "ttl_sec": 30,
        }


def _default_prior_geopose() -> Dict[str, Any]:
    stamp = SpatialDDSValidator.now_time()
    return {
        "lat_deg": DEFAULT_LAT,
        "lon_deg": DEFAULT_LON,
        "alt_m": DEFAULT_ALT,
        "q": [0.4967, -0.0336, -0.0585, 0.8653],
        # 1.7 removed GeoPose.frame_kind / frame_ref: orientation is fixed to
        # the local ENU tangent frame at the encoded position.
        "stamp": stamp,
        "cov": "COV_NONE",
    }


def _env_domain_id() -> Optional[int]:
    value = os.getenv("SPATIALDDS_DDS_DOMAIN", "")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_json(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw


class DDSEventBroadcaster:
    def __init__(self) -> None:
        self._queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._clients: set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, event: Dict[str, Any]) -> None:
        if not self._loop:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            dead: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)


def _emit_dds_event(event: Dict[str, Any]) -> None:
    broadcaster.emit(event)


def _wait_for(queue_obj: queue.Queue, msg_type: str, timeout: float) -> Optional[object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        try:
            envelope = queue_obj.get(timeout=remaining)
        except queue.Empty:
            continue
        if envelope.msg_type == msg_type:
            return envelope
    return None


def _lock(lock_queue: queue.Queue) -> None:
    lock_queue.get()


def _unlock(lock_queue: queue.Queue) -> None:
    lock_queue.put(True)


app = FastAPI(title="SpatialDDS Bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge = SpatialDDSBridge()
broadcaster = DDSEventBroadcaster()
client_mgr = ClientManager(TopicRouter())
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_publisher = None  # _BrowserPublisher (lazy)
_envelope_sub = None  # _StreamPump (typed readers, discovered from announces)
_total_dispatched = 0
_start_time_ns = time.time_ns()
ALLOW_PUBLISH = os.getenv("SPATIALDDS_BRIDGE_ALLOW_PUBLISH", "1") not in ("0", "false", "no")
STATIC_DIR = os.getenv("SPATIALDDS_BRIDGE_STATIC_DIR", str(_HERE / "static"))


# The stream pump calls ``_emit_dds_event`` for every typed sample, and this
# fans out to BOTH the /v1/stream broadcaster (raw, all clients) and the
# per-client ``ClientManager.dispatch`` for /ws subscribers.
_legacy_emit = _emit_dds_event


def _emit_dds_event(event: Dict[str, Any]) -> None:  # noqa: F811 — intentional override
    _legacy_emit(event)
    msg_type = event.get("msg_type") or ""
    topic = event.get("logical_topic") or ""
    payload = event.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {"_raw": payload}
    payload = payload if isinstance(payload, dict) else {}
    if _event_loop is None or not topic:
        return
    stamp_ns = int(event.get("ts", time.time()) * 1_000_000_000)

    async def _go():
        global _total_dispatched
        sent = await client_mgr.dispatch(topic, msg_type, payload, stamp_ns)
        _total_dispatched += sent

    _event_loop.call_soon_threadsafe(asyncio.ensure_future, _go())


def _stream_callback(type_name: str, logical_topic: str,
                     payload: Dict[str, Any], stamp_ns: int) -> None:
    """
    ``StreamSubscriber`` callback: one typed sample, as JSON for the browser.

    This is the only thing that reaches a WebSocket client, so what a client
    sees is what the bus carried — nothing else. The bridge used to also
    announce its own outbound requests here, before writing them, under the
    demo-private names ``LOCALIZE_REQUEST`` and ``CATALOG_QUERY``. That put a
    line on the stream for a sample that had not been written yet, under a
    name no announce declares, and every request appeared twice: once as the
    bridge's intention and once as the sample itself.

    This is the JSON edge. The bus carries real types; everything a
    WebSocket client sees is produced here, in the shape the /ws protocol
    has always used. ``msg_type`` keeps its place in that protocol — its
    value is now the announced 3.3.2 type rather than a demo-private label,
    which is strictly more information for the same field.
    """
    _emit_dds_event({
        "ts": stamp_ns / 1_000_000_000.0 if stamp_ns else time.time(),
        "dir": "rx",
        "domain": bridge._domain_id,
        "msg_type": type_name,
        "logical_topic": logical_topic,
        "request_id": "",
        "payload": payload,
    })


def _announce_callback(service_id: str, announce: Dict[str, Any]) -> None:
    """
    Announces reach browsers under a per-service logical topic.

    On the bus they are one keyed topic — Announce is @key service_id, so
    each service is its own instance. Browsers subscribe with a wildcard
    (``spatialdds/*/discovery/announce/v1``) and have since before the
    announce topic was consolidated, so the bridge names the service in the
    logical topic it hands out. The /ws protocol does not change.
    """
    name = announce.get("name") or service_id.removeprefix("svc:")
    _stream_callback("spatialdds/discovery/announce",
                     f"spatialdds/{name}/discovery/announce/v1",
                     announce, time.time_ns())


class _BrowserPublisher:
    """
    browser -> DDS, typed.

    A /ws publish names a logical_topic and a msg_type; the msg_type is
    resolved through the 3.3.2 registry and the payload is built into that
    class before it is written. A payload that is not a well-formed sample
    of its declared type is refused here, with a message the browser sees —
    under the envelope it went out as a well-formed string and failed, if at
    all, in some other process.
    """

    # 3.3.3 profile per registered type. A browser publishes on the lane the
    # spec assigns that type, not on whatever the bridge felt like.
    _PROFILES = {
        "geopose": "POSE_RT",
        "navsat_status": "POSE_RT",
        "planned_trajectory": "EVENT_RT",
        "entity_binding": "MAP_META",
        "spatial_event": "EVENT_RT",
        "video_frame": "VIDEO_LIVE",
        "radar_tensor": "RADAR_RT",
        "radar_detection": "RADAR_RT",
        "detection3d": "DET_RT",
        "rf_beam": "RF_BEAM_RT",
        "vps_query": "VPS_REQ",
        "vps_response": "VPS_RESP",
        "detection3d": "DET_RT",
        "framed_pose": "POSE_RT",
        "fused_track": "DET_RT",
        "oarc.fusion_coverage": "MAP_META",
        "oarc.catalog_query": "VPS_REQ",
        "oarc.catalog_response": "VPS_RESP",
    }
    DEFAULT_PROFILE = "EVENT_RT"

    def __init__(self, domain_id: int):
        from cyclonedds.domain import DomainParticipant

        self._participant = DomainParticipant(domain_id)
        self._writers: Dict[str, Any] = {}

    def publish(self, logical_topic: str, type_name: str,
                payload: Dict[str, Any]) -> None:
        from spatialdds_demo import topic_types, typed_transport as tt

        writer = self._writers.get(logical_topic)
        if writer is None:
            datatype = topic_types.resolve(type_name)
            writer = tt.TypedDictWriter(
                self._participant, logical_topic, datatype,
                self._PROFILES.get(type_name, self.DEFAULT_PROFILE))
            self._writers[logical_topic] = writer
        elif writer.datatype is not topic_types.resolve(type_name):
            raise ValueError(
                f"{logical_topic} already carries "
                f"{writer.datatype.__name__}; a topic is one type")
        writer.write(payload)


class _StreamPump:
    """
    Runs a ``StreamSubscriber`` on its own thread and feeds the fanout.

    The bridge is a FastAPI app, so DDS polling cannot live on the event
    loop; the callbacks hop back to it via ``call_soon_threadsafe``.
    """

    def __init__(self, domain_id: int, poll_interval: float = 0.02):
        from cyclonedds.domain import DomainParticipant

        from spatialdds_demo.stream import StreamSubscriber

        self._interval = poll_interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sub = StreamSubscriber(
            DomainParticipant(domain_id), _stream_callback,
            on_announce=_announce_callback,
        )

    @property
    def topics(self):
        return self._sub.topics

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sub.poll(stamp_ns=time.time_ns())
            except Exception:
                # One malformed sample must not take the bridge's whole
                # stream down; the next poll continues.
                pass
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _ensure_publisher():
    """Lazily build the typed writer pool for browser->DDS publishing."""
    global _publisher
    if _publisher is not None:
        return _publisher
    if _event_loop is None:
        return None
    _publisher = _BrowserPublisher(bridge.ensure_transport())
    return _publisher


@app.on_event("startup")
def on_startup() -> None:
    global _event_loop, _envelope_sub
    require_dds_env()
    domain_id = _env_domain_id()
    if domain_id is None:
        raise RuntimeError("SPATIALDDS_DDS_DOMAIN is required")
    bridge._domain_id = domain_id
    bridge._start_transport(domain_id)
    loop = asyncio.get_event_loop()
    _event_loop = loop
    broadcaster.attach_loop(loop)
    loop.create_task(broadcaster.run())

    # Typed reader per announced lane, discovered from announces — this is
    # the streaming-side fanout to /v1/stream + /ws. The VPS and catalogue
    # request/reply pairs correlate themselves, on their own typed topics.
    _envelope_sub = _StreamPump(domain_id)
    _envelope_sub.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    global _envelope_sub
    if _envelope_sub is not None:
        try:
            _envelope_sub.stop()
        except Exception:
            pass
        _envelope_sub = None


@app.get("/health")
def health() -> Dict[str, Any]:
    domain_id = bridge.ensure_transport()
    announce = bridge.latest_announce(timeout=1.0)
    return {
        "status": "ok",
        "dds_domain": domain_id,
        "announce": announce,
    }


@app.post("/v1/localize")
def localize(payload: Dict[str, Any]) -> Dict[str, Any]:
    prior = payload.get("prior_geopose") if isinstance(payload, dict) else None
    service_id = payload.get("service_id") if isinstance(payload, dict) else None
    try:
        return bridge.localize(prior, service_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/v1/catalog/query")
def catalog_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    geopose = payload.get("geopose") if isinstance(payload, dict) else None
    if not geopose:
        raise HTTPException(status_code=400, detail="geopose required")
    if "expr" in payload:
        raise HTTPException(
            status_code=400,
            detail=(
                "'expr' was removed in SpatialDDS 1.7; pass 'kind_in': "
                "[\"overlay\", \"poi\", \"mesh\"] instead"
            ),
        )
    kind_in = payload.get("kind_in")
    limit = int(payload.get("limit", 20) or 20)
    try:
        return bridge.catalog_query(geopose, kind_in=kind_in, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.websocket("/v1/stream")
async def stream(websocket: WebSocket) -> None:
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect(websocket)


# ─── Generic protocol (new) ──────────────────────────────────────────────────


@app.get("/api/topics")
def api_topics(stale_threshold_s: float = 30.0) -> Dict[str, Any]:
    """Topics seen on the bus within ``stale_threshold_s`` seconds."""
    topics = client_mgr.router.get_topics(stale_threshold_s=stale_threshold_s)
    return {
        "topics": [
            {
                "logical_topic": t.logical_topic,
                "msg_type": t.msg_type,
                "last_seen_ns": t.last_seen_ns,
                "rate_hz": round(t.rate_hz, 2),
                "message_count": t.message_count,
            }
            for t in topics
        ],
    }


@app.get("/api/stats")
def api_stats() -> Dict[str, Any]:
    return {
        "uptime_s": round((time.time_ns() - _start_time_ns) / 1e9, 1),
        "clients_connected": client_mgr.client_count,
        "total_dispatched": _total_dispatched,
        "topics_active": len(client_mgr.router.get_topics()),
        "dds_domain": bridge._domain_id,
        "publish_enabled": ALLOW_PUBLISH,
        "announce_cache": bridge.announce_stats(),
    }


# ─── Spec discovery, Layer 1.5 (HTTP binding) ────────────────────────────────
#
# The bridge translates: an HTTP search becomes a real `CoverageQuery` on the
# well-known discovery topic, and the services answer it themselves. §3.3 calls
# the HTTP and DDS bindings independent mechanisms that SHOULD agree, and for a
# gateway fronting services that live on DDS, agreeing by *asking them* is the
# honest reading — and the only one where discovery is visible on the bus
# alongside the localize and catalogue exchanges it precedes.
#
# The cache remains the fallback. A deployment whose services answer no
# coverage queries still resolves, from the retained announces this bridge
# holds, rather than reporting an empty world.
#
# Semantics — matching, filtering, pagination, manifest assembly — stay in
# spatialdds_demo/discovery_http.py, shared with ar_demo/http_binding.py. Only
# the *source* of the records differs, which is what has always separated the
# two servers.


def _served_manifest(record) -> Optional[Dict[str, Any]]:
    """
    Serve-or-synthesize: if this deployment hosts an authored manifest for the
    announce's manifest_uri, return that document verbatim; otherwise return
    None and let the core synthesize one from the announce.

    Uses the same resolver the demo client uses, so "hosted here" means exactly
    what it means everywhere else in the repo.
    """
    uri = record.manifest_uri
    if not uri:
        return None
    try:
        manifest, status = resolve_manifest(uri)
    except Exception:
        return None
    if not manifest:
        return None
    # Debug only. Which path produced a result is not part of the response.
    print(f"discovery: serving authored manifest for {uri} ({status.get('mode')})")
    return manifest


def _discovery_records(payload: Dict[str, Any]):
    """
    Ask the bus who covers this area; fall back to the cache if nobody answers.

    The normalized request is what goes on the wire, so the geohash shorthand
    and an omitted `coverage_frame_ref` reach the services as the coverage the
    spec says they mean.
    """
    normalized = normalize_search_request(payload)
    try:
        records = bridge.coverage_records(
            normalized["coverage"], normalized["coverage_frame_ref"])
    except Exception as exc:                     # bus unavailable, mid-restart
        print(f"discovery: coverage query failed ({exc}); using announce cache")
        return bridge.announce_records()
    if records is None:
        print("discovery: no CoverageResponse; using announce cache")
        return bridge.announce_records()
    return records


@app.post("/.well-known/spatialdds/search")
def wellknown_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return discovery_search(
            _discovery_records(payload), payload, manifest_provider=_served_manifest
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@app.get("/.well-known/spatialdds/search")
def wellknown_search_geohash(geohash: str, kind: Optional[str] = None) -> Dict[str, Any]:
    """
    The GET convenience form, which §3.3.0 makes REQUIRED alongside POST for
    interoperability with the Geospatial DNS-SD binding: "The GET form is
    equivalent to a POST with `{"geohash": "{geohash}"}` (and optional `kind`
    filter). The response format is identical."

    So it is exactly that — the same body, through the same call — rather than
    a second path that has to be kept in step with the first.
    """
    body: Dict[str, Any] = {"geohash": geohash}
    if kind:
        body["kind"] = [kind]
    return wellknown_search(body)


@app.get("/.well-known/spatialdds/bootstrap")
def wellknown_bootstrap() -> Dict[str, Any]:
    return bootstrap_manifest()


@app.websocket("/ws")
async def ws_generic(websocket: WebSocket) -> None:
    """Subscribe-based WebSocket protocol. See README for the message schema."""
    await websocket.accept()

    async def send_json(payload: dict) -> None:
        await websocket.send_json(payload)

    session = client_mgr.add_client(send_json)
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError("expected JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                await send_json({"type": "error", "message": f"Invalid JSON: {exc}"})
                continue

            mtype = str(msg.get("type") or "").lower()
            if mtype == "subscribe":
                resp = client_mgr.handle_subscribe(session, msg)
                await send_json(resp)
            elif mtype == "unsubscribe":
                resp = client_mgr.handle_unsubscribe(session, msg)
                await send_json(resp)
            elif mtype == "ping":
                await send_json({
                    "type": "pong",
                    "server_time_ns": time.time_ns(),
                    "clients_connected": client_mgr.client_count,
                    "messages_dispatched": _total_dispatched,
                })
            elif mtype == "list_topics":
                topics = client_mgr.router.get_topics()
                await send_json({
                    "type": "topics",
                    "topics": [
                        {
                            "logical_topic": t.logical_topic,
                            "msg_type": t.msg_type,
                            "last_seen_ns": t.last_seen_ns,
                            "rate_hz": round(t.rate_hz, 2),
                            "message_count": t.message_count,
                        }
                        for t in topics
                    ],
                })
            elif mtype == "publish":
                if not ALLOW_PUBLISH:
                    await send_json({
                        "type": "error",
                        "ref_id": msg.get("id", ""),
                        "message": "Publishing disabled (SPATIALDDS_BRIDGE_ALLOW_PUBLISH=0)",
                    })
                    continue
                logical_topic = str(msg.get("logical_topic") or "")
                msg_type_str = str(msg.get("msg_type") or "")
                payload = msg.get("payload") or {}
                if not logical_topic or not msg_type_str:
                    await send_json({
                        "type": "error",
                        "ref_id": msg.get("id", ""),
                        "message": "publish requires logical_topic and msg_type",
                    })
                    continue
                pub = _ensure_publisher()
                if pub is None:
                    await send_json({
                        "type": "error",
                        "ref_id": msg.get("id", ""),
                        "message": "Publisher not initialized",
                    })
                    continue
                try:
                    pub.publish(logical_topic, msg_type_str, payload)
                    session.messages_received += 1
                    await send_json({
                        "type": "published",
                        "msg_type": msg_type_str,
                        "logical_topic": logical_topic,
                        "status": "ok",
                    })
                except Exception as exc:
                    await send_json({
                        "type": "error",
                        "ref_id": msg.get("id", ""),
                        "message": f"publish failed: {exc}",
                    })
            else:
                await send_json({
                    "type": "error",
                    "message": f"Unknown message type: {mtype!r}",
                })
    finally:
        client_mgr.remove_client(session.client_id)


# Mount static dashboard if a directory exists.
if Path(STATIC_DIR).is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    _static_dir = Path(STATIC_DIR)

    # Landing page: 2D canvas top-down intersection viz. The old
    # topic-list debug page lives at /debug.
    @app.get("/")
    def _root_index():
        return FileResponse(_static_dir / "index.html")

    @app.get("/debug")
    def _debug_index():
        return FileResponse(_static_dir / "debug.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8088, reload=False)
