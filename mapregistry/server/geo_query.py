# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""Coarse GNSS vs map coverage — ``geo_query.strategy: standard`` only.

Not supported in this OpenVPS release: antimeridian, high-latitude, polar_cap
(deferred via ``geodetic_coverage.geo_query`` on the artifact; rejected at ingest).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from coverage_schema import MapCoverageRecord

_EARTH_RADIUS_M = 6_371_000.0


def query_uncertainty_deg(lat: float, radius_m: float) -> tuple[float, float]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = max(1.0, 111_320.0 * abs(math.cos(math.radians(lat))))
    return radius_m / m_per_deg_lat, radius_m / m_per_deg_lon


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _ring_contains_point(lon: float, lat: float, ring: List[Any]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        pi = ring[i]
        pj = ring[j]
        if not (isinstance(pi, (list, tuple)) and isinstance(pj, (list, tuple)) and len(pi) >= 2 and len(pj) >= 2):
            j = i
            continue
        xi, yi = float(pi[0]), float(pi[1])
        xj, yj = float(pj[0]), float(pj[1])
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def point_in_geo_footprint(lon: float, lat: float, footprint: Dict[str, Any]) -> bool:
    """GeoJSON Polygon or MultiPolygon exterior rings only (RFC 7946 [lon, lat])."""
    gtype = footprint.get("type")
    coords = footprint.get("coordinates")
    if not isinstance(coords, list):
        return False
    if gtype == "Polygon":
        if not coords:
            return False
        ring = coords[0]
        return isinstance(ring, list) and _ring_contains_point(lon, lat, ring)
    if gtype == "MultiPolygon":
        for poly in coords:
            if not isinstance(poly, list) or not poly:
                continue
            ring = poly[0]
            if isinstance(ring, list) and _ring_contains_point(lon, lat, ring):
                return True
        return False
    return False


def record_intersects_query(
    rec: MapCoverageRecord,
    lat: float,
    lon: float,
    radius_m: float,
    alt: Optional[float] = None,
    alt_radius_m: Optional[float] = None,
) -> bool:
    ga = rec.geo_aabb
    if ga is None:
        return False
    dlat, dlon = query_uncertainty_deg(lat, radius_m)
    q_min_lat, q_max_lat = lat - dlat, lat + dlat
    q_min_lon, q_max_lon = lon - dlon, lon + dlon

    if ga.lat_max < q_min_lat or ga.lat_min > q_max_lat:
        return False
    if ga.lon_max < q_min_lon or ga.lon_min > q_max_lon:
        return False

    if alt is not None:
        vr = alt_radius_m if alt_radius_m is not None and alt_radius_m > 0.0 else 0.0
        if alt + vr < ga.alt_min or alt - vr > ga.alt_max:
            return False

    if rec.geo_footprint is not None:
        if not point_in_geo_footprint(lon, lat, rec.geo_footprint):
            return False

    return True


def rank_distance_m(rec: MapCoverageRecord, lat: float, lon: float) -> float:
    ga = rec.geo_aabb
    if ga is None:
        return float("inf")
    cx = (ga.lat_min + ga.lat_max) / 2
    cy = (ga.lon_min + ga.lon_max) / 2
    return haversine_m(lat, lon, cx, cy)
