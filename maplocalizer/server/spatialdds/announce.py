# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
"""
Discovery: what this VPS advertises, and when it declines to.

`Announce` is keyed on `service_id` and published RELIABLE + TRANSIENT_LOCAL + KEEP_LAST(1),
so a late joiner receives the current announce of every live service and disposing the
instance means "this service is gone". `ttl_sec` maps onto DDS Lifespan, so an instance that
dies without disposing ages off the bus rather than lingering.

**A map is announced only when it is both loaded and georeferenced.** The second condition is
not obvious and is easy to get wrong in the permissive direction. Since upstream b2dff1f a
map gets a metric scale automatically during mapping, but its geodetic fields stay null until
someone georeferences it — so a freshly built map is localizable, metric, and has no position
on Earth. Coverage in 1.7 is entirely geographic, so such a map has nothing truthful to put in
a CoverageElement. Announcing it with empty or global coverage would be worse than silence: it
would match every coverage query and then return a pose no client can place. It stays fully
usable over HTTP and to a DDS client that already knows it; it is simply not discoverable.

Coverage is the hull of the registered camera positions, not of the point cloud. Camera
positions are the poses localization is known to work from, which is what coverage means. A
point-cloud hull is wrong in both directions at once — it reaches out to distant observed
features like building tops across a plaza, and falls short along stretches that were walked
but are poorly textured — so padding cannot correct it.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from oscp.geopose_utils import enu_to_geodetic

log = logging.getLogger("openvps.spatialdds")

# Metres of horizontal padding around the camera hull. Coverage is a discovery hint, not a
# guarantee: a client that discovers a VPS and then gets VPS_FAILED has a worse time than one
# that never discovered it, so this errs outward.
DEFAULT_COVERAGE_PAD_M = 15.0

SERVICE_KIND_VPS = "VPS"
TOPIC_ANNOUNCE = "spatialdds/discovery/announce/v1"
QOS_ANNOUNCE = "DISCOVERY_ANNOUNCE"
DEFAULT_TTL_SEC = 300


def camera_centres_map_frame(reconstruction) -> List[np.ndarray]:
    """Camera centres of every registered image, in the map's own frame."""
    centres = []
    for img in reconstruction.images.values():
        try:
            centres.append(np.asarray(img.projection_center(), dtype=float))
        except Exception:
            # pycolmap moved this accessor between versions; the localizer pins 3.13 but the
            # fallback costs nothing and a silent empty hull would be worse than a retry.
            centres.append(np.asarray(img.cam_from_world.inverse().translation, dtype=float))
    return centres


def coverage_bbox_wgs84(
    reconstruction,
    map_to_enu: np.ndarray,
    geodetic_ref,
    pad_m: float = DEFAULT_COVERAGE_PAD_M,
) -> Optional[Tuple[float, float, float, float]]:
    """
    `[west, south, east, north]` in degrees, or None when the map has no geodetic anchor.

    The chain is the one the localizer already uses for a pose: map frame through
    `map_to_enu` — which carries the scale, so ENU comes out in metres — then
    `enu_to_geodetic` about the anchor. Padding is applied in ENU, where metres are metres,
    rather than in degrees, where a fixed delta means different distances by latitude.
    """
    if geodetic_ref is None:
        return None
    centres = camera_centres_map_frame(reconstruction)
    if not centres:
        return None

    enu = []
    for c in centres:
        p = np.ones(4)
        p[:3] = c
        enu.append((map_to_enu @ p)[:3])
    e = np.asarray(enu)

    lo = e.min(axis=0) - pad_m
    hi = e.max(axis=0) + pad_m

    # Convert the padded ENU corners, not the raw extents: the padding has to be metric.
    lat_lo, lon_lo, _ = enu_to_geodetic(lo[0], lo[1], 0.0,
                                        geodetic_ref.lat, geodetic_ref.lon, geodetic_ref.h)
    lat_hi, lon_hi, _ = enu_to_geodetic(hi[0], hi[1], 0.0,
                                        geodetic_ref.lat, geodetic_ref.lon, geodetic_ref.h)
    west, east = sorted((lon_lo, lon_hi))
    south, north = sorted((lat_lo, lat_hi))
    return (west, south, east, north)


def build_announce(
    service_id: str,
    org: str,
    map_id: str,
    bbox: Sequence[float],
    manifest_uri: str,
    *,
    min_inliers: int,
    scale_factor: Optional[float],
    ttl_sec: int = DEFAULT_TTL_SEC,
    transforms: Optional[list] = None,
) -> dict:
    """
    The announce as a dict, ready for `json_mapping.from_json` onto `disco::Announce`.

    Built as a dict rather than the typed object because the demo's mapping is the tested
    path onto these types, and its union handling refuses a case name the type does not have
    — which a hand-built object would accept silently.
    """
    hints = [
        {"key": "openvps.map_id", "value": str(map_id)},
        {"key": "openvps.min_inliers", "value": str(int(min_inliers))},
    ]
    if scale_factor is not None:
        # Until FrameRef carries scale natively, this is the only place a discovering client
        # can learn the map frame's units without first making a query.
        hints.append({"key": "openvps.coord_scale_m_per_unit", "value": repr(float(scale_factor))})

    return {
        "service_id": service_id,
        "name": f"OpenVPS {map_id}",
        "kind": SERVICE_KIND_VPS,
        "version": "1.7",
        "org": org,
        "hints": hints,
        "caps": {
            "supported_profiles": [],
            "preferred_profiles": ["spatial.core/1.7", "spatial.argeo/1.7"],
            "features": ["blob.crc32"],
        },
        # Advertise vps_response, not geopose. The spec's own §3.3.4 example says `geopose`
        # here, which predates the batch-3 addition of the vps_response registry row and was
        # never swept; a client filtering on the registered type would not find this service.
        "topics": [
            {"name": "spatialdds/vps/query/v1", "type": "vps_query", "version": "v1",
             "qos_profile": "VPS_REQ", "target_rate_hz": 0.0, "max_chunk_bytes": 65535},
            {"name": "spatialdds/vps/result/v1", "type": "vps_response", "version": "v1",
             "qos_profile": "VPS_RESP", "target_rate_hz": 0.0, "max_chunk_bytes": 0},
        ],
        # Every member is set, including the ones this service does not use. They are real
        # struct members, not optional keys, and the presence flags are what say which
        # carry meaning — so a circle of radius zero with has_circle false is the correct
        # way to not have a circle.
        "coverage": [{
            "has_crs": True, "crs": "EPSG:4326",
            "has_bbox": True, "bbox": list(bbox),
            # Aabb3 is a struct of two Vec3, not a flat six-element array. A list of
            # six serialises to nothing useful and fails at write time, not at build.
            "has_aabb": False,
            "aabb": {"min_xyz": [0.0, 0.0, 0.0], "max_xyz": [0.0, 0.0, 0.0]},
            "has_circle": False,
            "circle_center": [0.0, 0.0, 0.0],
            "circle_radius_m": 0.0,
            "global": False,
            "has_frame_ref": False,
            "frame_ref": {"uuid": "", "fqn": "", "has_coord_convention": False,
                          "coord_convention": "ENU"},
            "has_coverage_window": False,
            "coverage_window_start": {"sec": 0, "nanosec": 0},
            "coverage_window_end": {"sec": 0, "nanosec": 0},
        }],
        "coverage_frame_ref": {
            "uuid": "earth-fixed", "fqn": "earth-fixed",
            "has_coord_convention": True, "coord_convention": "ENU",
        },
        "has_coverage_eval_time": False,
        "coverage_eval_time": {"sec": 0, "nanosec": 0},
        "transforms": transforms or [],
        "manifest_uri": manifest_uri,
        "auth_hint": "",
        "stamp": {"sec": 0, "nanosec": 0},
        "ttl_sec": int(ttl_sec),
        "coverage_source_ids": [],
    }


class ServiceAnnouncer:
    """
    Publishes the announce for whichever map the DDS path currently serves, and only then.

    One announce, not one per loaded map. Several maps can be resident since upstream added
    the LRU pool, but `VpsRequest` has no map field, so the DDS path answers from
    `currentMapId` and announcing anything else would advertise a map this service will not
    localize against. Announcing the map it actually serves is the only honest option.

    `service_id` follows the spec's persistent/revision split (Appendix F): the base is the
    stable identifier a client pins on, and `;v=<map_id>` makes each map a comparable
    revision of it. Since `Announce` is keyed on the whole string, swapping maps disposes one
    instance and creates another — which is what a keyed announce with dispose is for, and
    why the two are legibly the same service at two revisions rather than two services.
    """

    def __init__(self, participant, service_id_base: str, org: str,
                 *, pad_m: float = DEFAULT_COVERAGE_PAD_M, ttl_sec: int = DEFAULT_TTL_SEC):
        from spatialdds_demo import typed_transport as tt
        from spatialdds_idl.spatial.disco import Announce

        self._Announce = Announce
        self._tt = tt
        self._base = service_id_base.split(";", 1)[0]
        self._org = org
        self._pad_m = pad_m
        self._ttl = ttl_sec
        self._writer = tt.make_writer(
            participant, TOPIC_ANNOUNCE, Announce, QOS_ANNOUNCE, lifespan_sec=float(ttl_sec))
        # (service_id, payload dict, Announce sample), or None when nothing is announced.
        # The payload is kept beside the sample so a refresh can re-stamp and rebuild it
        # without re-deriving coverage; see _publish.
        self._current = None
        self._last_refresh = 0.0

    def service_id_for(self, map_id: str) -> str:
        return f"{self._base};v={map_id}"

    def set_map(self, map_id: str, localizer) -> bool:
        """
        Announce ``map_id``. Returns False when it is not announceable and says why.

        Not announceable means no geodetic anchor: since b2dff1f a map gets metric scale
        during mapping but stays ungeoreferenced until someone georeferences it, and coverage
        in 1.7 is entirely geographic. Such a map is localizable and has no position on
        Earth, so there is nothing truthful to advertise. It stays usable over HTTP and to a
        client that already knows it.
        """
        import time as _t
        from spatialdds_demo.json_mapping import from_json

        mt = getattr(localizer, "map_transform_info", None)
        if mt is None or mt.geodetic_ref is None:
            log.info("map %s has no geodetic anchor; not announcing it", map_id)
            self.clear()
            return False

        bbox = coverage_bbox_wgs84(
            localizer.reconstruction, mt.map_to_enu_transform, mt.geodetic_ref, self._pad_m)
        if bbox is None:
            log.info("map %s produced no coverage box; not announcing it", map_id)
            self.clear()
            return False

        sid = self.service_id_for(map_id)
        if self._current is not None and self._current[0] != sid:
            self.clear()

        scale = None
        fr = getattr(mt, "frame_ref", None)
        if fr is not None and getattr(fr, "has_coord_scale", False) and fr.coord_scale:
            scale = float(fr.coord_scale.scale_factor)

        payload = build_announce(
            sid, self._org, map_id, bbox,
            f"spatialdds://{self._org}/{map_id}/service/vps",
            min_inliers=20, scale_factor=scale, ttl_sec=self._ttl,
            transforms=self._map_to_enu_transform_entry(mt, map_id),
        )
        self._publish(sid, payload)
        log.info("announced %s covering %s", sid, bbox)
        return True

    def _publish(self, sid: str, payload: dict) -> None:
        """
        Stamp with now, write, and remember. The only path that publishes an announce.

        Both the initial announce and every refresh go through here, so the stamp cannot
        drift from the write again. It did: `tick` used to re-write the stored sample, which
        refreshes the DDS Lifespan — each write does — but leaves `Announce.stamp` frozen at
        the moment the map was loaded. The two liveness signals then disagree, and a consumer
        applying the only backstop the spec states, that an announce is not to be used beyond
        `stamp + ttl_sec`, drops a service that is announcing every 150 s and answering
        requests. Discovery reports an empty deployment and nothing errors at either end.

        The payload is re-stamped rather than rebuilt. Rebuilding would re-walk the
        reconstruction for the coverage hull every refresh, and worse, would need a reference
        to the localizer held across the interval — which the LRU pool may have evicted by
        then, so it could announce a map no longer loaded. Re-stamping also makes "otherwise
        byte-identical to the previous announce" true by construction rather than by care.
        """
        import time as _t
        from spatialdds_demo.json_mapping import from_json

        now = _t.time()
        payload["stamp"] = {"sec": int(now), "nanosec": int((now % 1) * 1e9)}
        sample = from_json(self._Announce, payload)
        self._writer.write(sample)
        self._current = (sid, payload, sample)
        self._last_refresh = now

    def _map_to_enu_transform_entry(self, mt, map_id: str):
        """
        The map-to-earth relation, as a disco::Transform in the announce.

        Deliberately not core::FrameTransform: that type has no registered topic or QoS
        profile, and its T_parent_child runs parent-to-child with the global frame as
        parent, i.e. the inverse of what is held here. Transform's from/to needs no
        inversion. Rotation only — the scale is declared on the frame, so what remains is
        rigid and fits PoseSE3.
        """
        import numpy as _np
        from scipy.spatial.transform import Rotation as _R

        T = _np.asarray(mt.map_to_enu_transform, dtype=float)
        L = T[:3, :3]
        norms = _np.linalg.norm(L, axis=0)
        s = float(_np.mean(norms)) if _np.all(norms > 1e-12) else 1.0
        q = _R.from_matrix(L / s).as_quat()      # scipy returns x, y, z, w
        return [{
            "from": {"uuid": str(map_id), "fqn": f"openvps/hloc/{map_id}/colmap_world",
                     "has_coord_convention": True, "coord_convention": "CV"},
            "to": {"uuid": "earth-fixed", "fqn": "earth-fixed",
                   "has_coord_convention": True, "coord_convention": "ENU"},
            "pose": {"t": [float(T[0, 3]), float(T[1, 3]), float(T[2, 3])],
                     "q": [float(q[0]), float(q[1]), float(q[2]), float(q[3])]},
            "stamp": {"sec": 0, "nanosec": 0},
            "has_validity": False,
            "validity": {"from": {"sec": 0, "nanosec": 0}, "seconds": 0},
        }]

    def tick(self) -> None:
        """
        Re-announce at half the TTL, stamp included.

        Half, not the whole TTL, so a single dropped refresh does not expire the service.
        """
        import time as _t
        if self._current is None:
            return
        if _t.time() - self._last_refresh < self._ttl / 2.0:
            return
        sid, payload, _sample = self._current
        self._publish(sid, payload)

    def clear(self) -> None:
        """Dispose the announce, so consumers see removal rather than waiting out the TTL."""
        if self._current is None:
            return
        sid, _payload, sample = self._current
        self._current = None
        try:
            self._tt.dispose(self._writer, sample)
            log.info("disposed announce %s", sid)
        except Exception:
            log.exception("could not dispose announce %s", sid)

    def depart(self) -> None:
        self.clear()
