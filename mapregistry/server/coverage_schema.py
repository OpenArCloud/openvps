# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""Coverage artifact schema (coverage.json v1) and index helpers.

- ``volumes[]``: metric Aabb3 per ``frame_ref`` (``min_xyz`` / ``max_xyz``).
- ``geodetic_coverage``: optional WGS84 — ``geo_aabb``,
- ``geo_footprint``: (``Polygon`` |
  ``MultiPolygon`` on wire),
- ``geo_query``: optional ``strategy: standard`` ).
- ``geo_query.strategy``: ``standard`` is the only supported value for now (``antimeridian``, ``high_latitude``, ``polar_cap`` are reserved for future releases)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

CoverageStatus = Literal["ok", "missing", "invalid"]

GeoQueryStrategy = Literal["standard", "antimeridian", "high_latitude", "polar_cap"]

GEO_QUERY_STRATEGIES_SUPPORTED: frozenset[str] = frozenset({"standard"})

WGS84_ENU_FRAME_REF: Dict[str, str] = {
    "uuid": "OSCP:WGS84-ENU",
    "fqn": "OSCP:WGS84-ENU",
}

# Temperate maps only; antimeridian / high-lat / polar handled in future via geo_query.
MAX_ABS_LAT_SUPPORTED = 85.0


def map_colmap_frame_ref(map_id: str) -> Dict[str, str]:
    mid = str(map_id)
    return {"uuid": mid, "fqn": f"openvps/hloc/{mid}/colmap_world"}


def _frame_ref_ids(frame_ref: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(frame_ref, dict):
        return None, None
    uuid = frame_ref.get("uuid")
    fqn = frame_ref.get("fqn")
    u = str(uuid).strip() if uuid is not None else None
    f = str(fqn).strip() if fqn is not None else None
    return u or None, f or None


def frame_ref_is_wgs84_enu(frame_ref: Any) -> bool:
    uuid, fqn = _frame_ref_ids(frame_ref)
    return uuid == WGS84_ENU_FRAME_REF["uuid"] or fqn == WGS84_ENU_FRAME_REF["fqn"]


def frame_ref_is_map_colmap(frame_ref: Any, map_id: str) -> bool:
    expected = map_colmap_frame_ref(map_id)
    uuid, fqn = _frame_ref_ids(frame_ref)
    return uuid == expected["uuid"] or fqn == expected["fqn"]


class GeodeticAabb(BaseModel):
    """WGS84 axis-aligned limits (SpatialDDS §2.10); named fields only on wire."""

    lon_min: float
    lat_min: float
    alt_min: float
    lon_max: float
    lat_max: float
    alt_max: float

    def bbox2d(self) -> Tuple[float, float, float, float]:
        return self.lon_min, self.lat_min, self.lon_max, self.lat_max


def parse_geodetic_aabb(raw: Any) -> Optional[GeodeticAabb]:
    if not isinstance(raw, dict):
        return None
    try:
        model = GeodeticAabb(
            lon_min=float(raw["lon_min"]),
            lat_min=float(raw["lat_min"]),
            alt_min=float(raw["alt_min"]),
            lon_max=float(raw["lon_max"]),
            lat_max=float(raw["lat_max"]),
            alt_max=float(raw["alt_max"]),
        )
        if not all(
            math.isfinite(getattr(model, k))
            for k in ("lon_min", "lat_min", "alt_min", "lon_max", "lat_max", "alt_max")
        ):
            return None
        return model
    except (KeyError, TypeError, ValueError):
        return None


def validate_geo_footprint(raw: Any) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    gtype = raw.get("type")
    if gtype not in ("Polygon", "MultiPolygon"):
        return "geo_footprint.type must be Polygon or MultiPolygon"
    coords = raw.get("coordinates")
    if not isinstance(coords, list) or len(coords) == 0:
        return "geo_footprint.coordinates missing or empty"
    return None


def _parse_geo_query_strategy(block: Dict[str, Any]) -> Tuple[Optional[GeoQueryStrategy], Optional[str]]:
    raw = block.get("geo_query")
    if raw is None:
        return "standard", None
    if not isinstance(raw, dict):
        return None, "geo_query must be an object"
    strat = raw.get("strategy", "standard")
    if not isinstance(strat, str):
        return None, "geo_query.strategy must be a string"
    if strat not in GEO_QUERY_STRATEGIES_SUPPORTED:
        return None, (
            f"geo_query.strategy {strat!r} is not supported in this OpenVPS release "
            f"(supported: {sorted(GEO_QUERY_STRATEGIES_SUPPORTED)})"
        )
    return strat, None  # type: ignore[return-value]


def _standard_geo_limits_ok(geo_aabb: GeodeticAabb, block: Dict[str, Any]) -> Optional[str]:
    if block.get("crosses_antimeridian"):
        return "crosses_antimeridian maps are not supported in this OpenVPS release"
    if geo_aabb.lon_max - geo_aabb.lon_min > 180.0:
        return "geo_aabb lon span > 180° (antimeridian) is not supported in this OpenVPS release"
    lat_extent = max(abs(geo_aabb.lat_min), abs(geo_aabb.lat_max))
    if lat_extent > MAX_ABS_LAT_SUPPORTED:
        return (
            f"|lat| > {MAX_ABS_LAT_SUPPORTED}° is not supported in this OpenVPS release "
            "(high-latitude / polar coverage deferred)"
        )
    return None


def extract_geodetic_index_fields(
    data: Dict[str, Any],
) -> Tuple[Optional[GeodeticAabb], Optional[Dict[str, Any]], Optional[GeoQueryStrategy], Optional[str]]:
    """Parse ``geodetic_coverage`` for index fields.

    Returns ``(geo_aabb, geo_footprint, geo_query_strategy, error)``.
    """
    block = data.get("geodetic_coverage")
    if block is None:
        return None, None, None, None
    if not isinstance(block, dict):
        return None, None, None, "geodetic_coverage must be an object"
    fr = block.get("frame_ref")
    if fr is not None and not frame_ref_is_wgs84_enu(fr):
        return None, None, None, "geodetic_coverage.frame_ref must be OSCP:WGS84-ENU when set"
    strategy, strat_err = _parse_geo_query_strategy(block)
    if strat_err:
        return None, None, None, strat_err
    geo_aabb = parse_geodetic_aabb(block.get("geo_aabb"))
    if geo_aabb is None:
        return None, None, None, "geodetic_coverage.geo_aabb is missing or invalid"
    lim_err = _standard_geo_limits_ok(geo_aabb, block)
    if lim_err:
        return None, None, None, lim_err
    gf = block.get("geo_footprint")
    geo_footprint: Optional[Dict[str, Any]] = None
    if gf is not None:
        if not isinstance(gf, dict):
            return None, None, None, "geo_footprint must be an object"
        fp_err = validate_geo_footprint(gf)
        if fp_err:
            return None, None, None, fp_err
        geo_footprint = gf
    return geo_aabb, geo_footprint, strategy, None


def volumes_include_map_frame(data: Dict[str, Any], map_id: str) -> bool:
    vols = data.get("volumes")
    if not isinstance(vols, list) or len(vols) == 0:
        return False
    for vol in vols:
        if not isinstance(vol, dict):
            continue
        if not frame_ref_is_map_colmap(vol.get("frame_ref"), map_id):
            continue
        aabb = vol.get("aabb")
        if not isinstance(aabb, dict):
            continue
        mn, mx = aabb.get("min_xyz"), aabb.get("max_xyz")
        if isinstance(mn, list) and isinstance(mx, list) and len(mn) == 3 and len(mx) == 3:
            return True
    return False


class MapCoverageRecord(BaseModel):
    """One map entry in map_registry.json."""

    model_config = {"extra": "ignore"}

    schema_version: int = SCHEMA_VERSION
    map_id: str
    coverage_status: CoverageStatus = "missing"
    geo_aabb: Optional[GeodeticAabb] = None
    geo_footprint: Optional[Dict[str, Any]] = None
    geo_query_strategy: Optional[GeoQueryStrategy] = None
    volumes: Optional[List[Dict[str, Any]]] = None
    model_signature: Optional[str] = None
    localization_model_signature: Optional[str] = None
    coverage_schema_version: Optional[int] = None
    ingest_error: Optional[str] = None
    updated_at: str = ""

    def geo_bbox2d(self) -> Optional[Tuple[float, float, float, float]]:
        if self.geo_aabb is None:
            return None
        return self.geo_aabb.bbox2d()

    def eligible_for_geo_query(self) -> bool:
        return (
            self.coverage_status == "ok"
            and self.geo_aabb is not None
            and (self.geo_query_strategy is None or self.geo_query_strategy == "standard")
        )


class RegistryIndex(BaseModel):
    schema_version: int = SCHEMA_VERSION
    maps: Dict[str, MapCoverageRecord] = Field(default_factory=dict)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "maps": {k: v.model_dump(exclude_none=True) for k, v in self.maps.items()},
        }
