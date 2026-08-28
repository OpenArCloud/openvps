# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
"""
The SpatialDDS 1.7 VPS binding: `vps_query` in, `vps_response` out.

This is the request/reply binding the spec registers — `argeo::VpsRequest` and
`VpsResponse` correlated by `query_id` on the `VPS_REQ` / `VPS_RESP` profiles. Streaming was
considered and deferred; the reasoning is in the branch notes, and the short version is that
ARKit and ARCore already track continuously on-device and need the VPS only for periodic
absolute fixes, which is structurally a query.

Query imagery never rides inline. `VpsRequest.query_blobs` carries `BlobRef`s and the bytes
arrive as `BlobChunk` samples on a separate topic, chunked at the 65,535-byte ceiling that
cyclonedds-python imposes on sequences. So a request is not servable when it arrives: it
waits until its blobs are whole. `PendingRequest` is that wait, and it is bounded in both
directions — by count, so a flood cannot grow the table, and by age, so a client that dies
mid-blob is reaped on time rather than on pressure.

Localization runs on one worker. The GPU serialises anyway, and the HTTP path is already
using it, so both surfaces queue through the same executor rather than contending through
the GIL. That does not fix the pre-existing problem of the HTTP handler calling a blocking
GPU routine on the event loop — it avoids making it worse.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from spatialdds_demo import blob as blobmod
from spatialdds_demo import typed_transport as tt
from spatialdds_demo.json_mapping import from_json
from spatialdds_demo.payloads import COV_NONE
from spatialdds_idl.builtin import Time as IdlTime
from spatialdds_idl.spatial.argeo import NodeGeo, VpsRequest, VpsResponse, VpsStatus
from spatialdds_idl.spatial.core import BlobChunk, GeoPose as IdlGeoPose

from spatialdds.frames import framed_pose_to_idl

log = logging.getLogger("openvps.spatialdds")

TOPIC_VPS_QUERY = "spatialdds/vps/query/v1"
TOPIC_VPS_RESULT = "spatialdds/vps/result/v1"
TOPIC_BLOB_CHUNK = "spatialdds/blob/chunk/v1"

QOS_VPS_REQ = "VPS_REQ"
QOS_VPS_RESP = "VPS_RESP"
QOS_BLOB = "GEOM_TILE"

# The role a query image announces itself under, per the VpsRequest IDL comment.
ROLE_QUERY_IMAGE = "vps/query-image"

# How long a request may sit waiting for its blobs, and how many may wait at once. A pose
# fix that arrives late is not a late success; it is a failure that cost GPU time.
DEFAULT_ASSEMBLY_TIMEOUT_S = 20.0
DEFAULT_MAX_PENDING = 32


def now_time() -> IdlTime:
    t = time.time()
    return IdlTime(sec=int(t), nanosec=int((t % 1) * 1e9))


@dataclass
class PendingRequest:
    """A request whose imagery has not fully arrived."""

    request: VpsRequest
    received_at: float
    needed_blobs: List[str]
    images: Dict[str, bytes] = field(default_factory=dict)

    def complete(self) -> bool:
        return all(b in self.images for b in self.needed_blobs)

    def age(self) -> float:
        return time.time() - self.received_at


@dataclass
class LocalizeOutcome:
    """What the localizer produced, in the localizer's own types."""

    framed_poses: list
    geoposes: list
    confidence: float
    map_id: str
    # False when the map has no geodetic anchor, in which case geoposes is empty and the
    # FramedPose is the whole of the useful answer.
    georeferenced: bool = True


class VpsService:
    """
    Serves `vps_query` from the bus.

    ``localize_fn`` takes (image_bytes, VpsRequest) and returns a LocalizeOutcome, or None
    when no fix was found. It is called on the caller's thread — `poll` is expected to run
    on a dedicated thread, not the event loop.
    """

    def __init__(
        self,
        participant,
        service_id: str,
        localize_fn: Callable[[bytes, VpsRequest], Optional[LocalizeOutcome]],
        *,
        assembly_timeout_s: float = DEFAULT_ASSEMBLY_TIMEOUT_S,
        max_pending: int = DEFAULT_MAX_PENDING,
        current_revision: Optional[Callable[[], Optional[str]]] = None,
    ):
        # The persistent identifier, without any ;v= suffix. The announce carries the
        # versioned form; see _addressed_to_us.
        self.service_id = service_id.split(";", 1)[0]
        self._current_revision = current_revision
        self._localize = localize_fn
        self._assembly_timeout = assembly_timeout_s
        self._max_pending = max_pending

        self._requests = tt.make_reader(participant, TOPIC_VPS_QUERY, VpsRequest, QOS_VPS_REQ)
        self._replies = tt.make_writer(participant, TOPIC_VPS_RESULT, VpsResponse, QOS_VPS_RESP)
        self._chunks = tt.make_reader(participant, TOPIC_BLOB_CHUNK, BlobChunk, QOS_BLOB)

        self._reassembler = blobmod.Reassembler()
        self._pending: Dict[str, PendingRequest] = {}
        # Blobs that finished before the request naming them arrived. Nothing orders two
        # DDS topics against each other, so this is the normal case, not a rare one: a
        # client that writes its chunks immediately after the request will often have them
        # delivered first. A taken sample is gone, so without this the image is silently
        # dropped and the request times out with the bytes already in hand.
        self._ready_blobs: Dict[str, Tuple[bytes, float]] = {}
        self._lock = threading.Lock()

    # -- wire in -----------------------------------------------------------------

    def poll(self) -> int:
        """One pass: take chunks, take requests, serve what is ready. Returns replies sent."""
        self._take_chunks()
        self._take_requests()
        return self._serve_ready()

    def _take_chunks(self) -> None:
        for chunk in tt.take_samples(self._chunks):
            try:
                data = self._reassembler.feed(chunk)
            except blobmod.CorruptChunk as exc:
                # A chunk whose CRC32 disagrees with its bytes. Drop it and let the request
                # time out rather than reassembling something that is not the image.
                log.warning("discarding corrupt chunk: %s", exc)
                continue
            if data is None:
                continue
            with self._lock:
                claimed = False
                for pending in self._pending.values():
                    if chunk.blob_id in pending.needed_blobs:
                        pending.images[chunk.blob_id] = data
                        claimed = True
                if not claimed:
                    self._park_blob(chunk.blob_id, data)

    def _addressed_to_us(self, service_id: str) -> bool:
        """
        Whether a request naming ``service_id`` is ours to answer.

        Appendix F splits an identifier in two: without ``;v=`` it is a persistent
        identifier, with it an immutable revision. The announce advertises the revision —
        base plus the map id — because that is what a client should pin. So a client that
        discovers this service and echoes back what it discovered sends the *versioned*
        form, and comparing it against the bare configured id rejects every discovered
        client. That happened: discovery worked, the service worked, and no request from a
        discovering client was ever answered, with no error on either side.

        Both forms are accepted, and the version is used for what it is actually good for:

        - empty        -> addressed to whoever is listening
        - base         -> whatever revision you are serving
        - base;v=<map> -> specifically that map; served only if it is the one loaded

        The last case is the map-mismatch rejection the contract asks for, without needing a
        field VpsRequest does not have.
        """
        if not service_id:
            return True
        base, _, revision = service_id.partition(";v=")
        if base != self.service_id:
            return False
        if not revision:
            return True
        current = self._current_revision() if self._current_revision else None
        return current is None or revision == current

    def _reply_service_id(self) -> str:
        """
        The identifier a reply carries: the revision that actually answered, when known.

        A client can then tell which map produced the pose without parsing the frame
        reference, and can notice the service moved on between request and reply.
        """
        current = self._current_revision() if self._current_revision else None
        return f"{self.service_id};v={current}" if current else self.service_id

    def _take_requests(self) -> None:
        for req in tt.take_samples(self._requests):
            if not self._addressed_to_us(req.service_id):
                # Either another VPS on this partition, or this one asked for a map it is
                # not serving. The first is not an error; the second is, and the client is
                # told so rather than left to time out.
                base, _, rev = req.service_id.partition(";v=")
                if base == self.service_id and rev:
                    self._reply_failed(req, f"map {rev} is not loaded")
                continue
            needed = [b.blob_id for b in req.query_blobs if b.role == ROLE_QUERY_IMAGE]
            if not needed:
                self._reply_failed(req, "no query image blob")
                continue
            with self._lock:
                if len(self._pending) >= self._max_pending:
                    self._reply_failed(req, "too many requests in flight")
                    continue
                p = PendingRequest(request=req, received_at=time.time(), needed_blobs=needed)
                # Adopt any blob that arrived ahead of this request.
                for b in needed:
                    parked = self._ready_blobs.pop(b, None)
                    if parked is not None:
                        p.images[b] = parked[0]
                self._pending[req.query_id] = p

    def _park_blob(self, blob_id: str, data: bytes) -> None:
        """Hold a blob whose request has not arrived, bounded by age then by count."""
        cutoff = time.time() - self._assembly_timeout
        for bid in [b for b, (_, t) in self._ready_blobs.items() if t < cutoff]:
            self._ready_blobs.pop(bid, None)
        while len(self._ready_blobs) >= self._max_pending:
            self._ready_blobs.pop(next(iter(self._ready_blobs)), None)
        self._ready_blobs[blob_id] = (data, time.time())

    def _serve_ready(self) -> int:
        with self._lock:
            ready = [p for p in self._pending.values() if p.complete()]
            stale = [p for p in self._pending.values()
                     if not p.complete() and p.age() > self._assembly_timeout]
            for p in ready + stale:
                self._pending.pop(p.request.query_id, None)

        for p in stale:
            log.info("request %s timed out waiting for imagery", p.request.query_id)
            self._reply_failed(p.request, "imagery incomplete")

        sent = 0
        for p in ready:
            image = p.images[p.needed_blobs[0]]
            try:
                outcome = self._localize(image, p.request)
            except Exception:
                log.exception("localization raised for %s", p.request.query_id)
                self._reply_failed(p.request, "localization error")
                sent += 1
                continue
            if outcome is None:
                self._reply_failed(p.request, "no fix")
            else:
                self._reply_success(p.request, outcome)
            sent += 1
        return sent

    # -- wire out ----------------------------------------------------------------

    def _reply_failed(self, req: VpsRequest, reason: str) -> None:
        """
        Every failure is VPS_FAILED.

        VpsStatus has three values and VpsResponse has no diagnostic field, so "wrong map",
        "no fix", "malformed blob" and "queue full" are indistinguishable to the client.
        The reason is logged because the log is the only place it exists. This is a real
        gap in the binding, written up for the spec; the operational cost is that a client
        cannot tell retryable from permanent, so the rational behaviour on any failure is
        to retry — which is worst when the service is already shedding.
        """
        log.info("VPS_FAILED for %s: %s", req.query_id, reason)
        self._replies.write(
            VpsResponse(
                query_id=req.query_id,
                service_id=self._reply_service_id(),
                status=VpsStatus.VPS_FAILED,
                has_node_geo=False,
                node_geo=_empty_node_geo(),
                confidence=0.0,
                has_rmse_m=False,
                rmse_m=0.0,
                stamp=now_time(),
            )
        )

    def _reply_success(self, req: VpsRequest, outcome: LocalizeOutcome) -> None:
        stamp = now_time()
        poses = [framed_pose_to_idl(fp, stamp) for fp in outcome.framed_poses[:8]]

        has_geo = bool(outcome.georeferenced and outcome.geoposes)
        node = NodeGeo(
            map_id=outcome.map_id,
            node_id=f"vps-fix/{req.query_id}",
            poses=poses,
            has_geopose=has_geo,
            geopose=_geopose_to_idl(outcome.geoposes[0], stamp) if has_geo else _empty_geopose(),
            source_id=self._reply_service_id(),
            seq=0,
            graph_epoch=0,
        )
        quality = req.quality_requirements if req.has_quality_requirements else None
        degraded = quality is not None and outcome.confidence < float(quality.min_confidence)
        self._replies.write(
            VpsResponse(
                query_id=req.query_id,
                service_id=self._reply_service_id(),
                status=VpsStatus.VPS_DEGRADED if degraded else VpsStatus.VPS_SUCCESS,
                has_node_geo=True,
                node_geo=node,
                confidence=float(outcome.confidence),
                # The PnP step surfaces no covariance, so there is no honest RMSE to give.
                has_rmse_m=False,
                rmse_m=0.0,
                stamp=stamp,
            )
        )


def _empty_node_geo() -> NodeGeo:
    return NodeGeo(map_id="", node_id="", poses=[], has_geopose=False,
                   geopose=_empty_geopose(), source_id="", seq=0, graph_epoch=0)


def _empty_geopose() -> IdlGeoPose:
    return IdlGeoPose(lat_deg=0.0, lon_deg=0.0, alt_m=0.0, q=[0.0, 0.0, 0.0, 1.0],
                      stamp=IdlTime(sec=0, nanosec=0), cov=from_json(_cov_type(), dict(COV_NONE)))


def _cov_type():
    from spatialdds_idl.spatial.core import CovMatrix
    return CovMatrix


def _geopose_to_idl(gp, stamp: IdlTime) -> IdlGeoPose:
    """
    The localizer's GeoPose onto the wire type.

    GeoPose is always ENU — the spec is normative that its quaternion is expressed in the
    local ENU tangent frame at the encoded position — so there is no convention to carry
    and no coord_convention to set. That is the asymmetry with FramedPose, whose frame
    governs its axes.
    """
    return IdlGeoPose(
        lat_deg=float(gp.position.lat),
        lon_deg=float(gp.position.lon),
        alt_m=float(gp.position.h),
        q=[float(gp.quaternion.x), float(gp.quaternion.y),
           float(gp.quaternion.z), float(gp.quaternion.w)],
        stamp=stamp,
        cov=from_json(_cov_type(), dict(COV_NONE)),
    )
