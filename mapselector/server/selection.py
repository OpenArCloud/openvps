# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

"""Location-hint extraction and map candidate ranking (MapRegistry client helpers)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Horizontal GNSS uncertainty for MapRegistry query (metres).
kDefaultHorizontalSearchRadius = 75.0
# When true, pass altitude from geolocationReadings to MapRegistry (alt + alt_radius_m).
kEnableVerticalSearch = False
# Vertical search window when vertical search is enabled (metres).
kDefaultVerticalSearchRadius = 15.0

@dataclass(frozen=True)
class GnssQuery:
    lat: float
    lon: float
    radius_m: float
    alt: Optional[float] = None
    alt_radius_m: Optional[float] = None


def _wgs84_from_prior_pose(prior: Dict[str, Any]) -> Optional[Tuple[float, float, Optional[float]]]:
    """lat, lon, optional h from GeoPoseResponse-shaped prior (geopose or geoposes[0])."""
    geopose = prior.get("geopose")
    if isinstance(geopose, dict):
        pos = geopose.get("position")
        if isinstance(pos, dict) and "lat" in pos and "lon" in pos:
            h_raw = pos.get("h")
            h = float(h_raw) if h_raw is not None else None
            return float(pos["lat"]), float(pos["lon"]), h
    geoposes = prior.get("geoposes")
    if isinstance(geoposes, list) and geoposes:
        first = geoposes[0]
        if isinstance(first, dict):
            pos = first.get("position")
            if isinstance(pos, dict) and "lat" in pos and "lon" in pos:
                h_raw = pos.get("h")
                h = float(h_raw) if h_raw is not None else None
                return float(pos["lat"]), float(pos["lon"]), h
    return None


def extract_prior_geopose_query(body: Dict[str, Any]) -> Optional[GnssQuery]:
    priors = body.get("priorPoses") or []
    if not isinstance(priors, list) or not priors:
        return None
    prior = priors[0]
    if not isinstance(prior, dict):
        return None
    coords = _wgs84_from_prior_pose(prior)
    if coords is None:
        return None
    lat, lon, h = coords
    radius = kDefaultHorizontalSearchRadius
    accuracy = prior.get("accuracy")
    if isinstance(accuracy, dict):
        acc = float(accuracy.get("position", 0) or 0)
        if acc > 1.0:
            radius = max(radius, acc)
    alt: Optional[float] = None
    alt_radius_m: Optional[float] = None
    if kEnableVerticalSearch and h is not None:
        alt = h
        alt_radius_m = kDefaultVerticalSearchRadius
    return GnssQuery(lat=lat, lon=lon, radius_m=radius, alt=alt, alt_radius_m=alt_radius_m)


def extract_location_query(body: Dict[str, Any]) -> Optional[GnssQuery]:
    """priorPoses first, then geolocationReadings."""
    q = extract_prior_geopose_query(body)
    if q is not None:
        return q
    return extract_gnss_query(body)


def extract_gnss_query(body: Dict[str, Any]) -> Optional[GnssQuery]:
    readings = (body.get("sensorReadings") or {}).get("geolocationReadings") or []
    if not readings:
        return None
    g = readings[0]
    lat = float(g.get("latitude", 0.0))
    lon = float(g.get("longitude", 0.0))
    radius = kDefaultHorizontalSearchRadius
    acc = float(g.get("accuracy", 0.0) or 0.0)
    if acc > 1.0:
        radius = max(radius, acc)
    alt: Optional[float] = None
    alt_radius_m: Optional[float] = None
    if kEnableVerticalSearch and "altitude" in g and g.get("altitude") is not None:
        alt = float(g["altitude"])
        alt_radius_m = kDefaultVerticalSearchRadius
    return GnssQuery(lat=lat, lon=lon, radius_m=radius, alt=alt, alt_radius_m=alt_radius_m)


def candidate_map_ids(query_response: Dict[str, Any], limit: int) -> List[str]:
    candidates = query_response.get("candidates") or []
    ids: List[str] = []
    for item in candidates[: max(limit, 0)]:
        if isinstance(item, dict) and item.get("map_id") is not None:
            ids.append(str(item["map_id"]))
    return ids


def localization_attempt_success(status_code: int, body: bytes, content_type: Optional[str]) -> bool:
    """True when MapLocalizer returned a usable GeoPose result."""
    if status_code != 200:
        return False
    if content_type and "json" in content_type.lower():
        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return True
        if not isinstance(data, dict):
            return True
        if data.get("ERROR"):
            return False
        if data.get("geopose") or data.get("geoposes") or data.get("poses"):
            return True
        if data.get("framedPoses") or data.get("framed_poses"):
            return True
        return "ERROR" not in data
    return True


def should_try_next_map(status_code: int, body: bytes, content_type: Optional[str]) -> bool:
    """Whether multi-try should continue with the next registry candidate."""
    if localization_attempt_success(status_code, body, content_type):
        return False
    if status_code == 404:
        return True
    if status_code == 500:
        try:
            if content_type and "json" in (content_type or "").lower():
                data = json.loads(body.decode("utf-8"))
                err = str(data.get("ERROR", "")).lower()
                if "could not localize" in err or "failed to load map" in err:
                    return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return True
    return False