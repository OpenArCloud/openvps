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
            "has_aabb": False, "aabb": [0.0] * 6,
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
