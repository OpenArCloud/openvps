# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""Ingest coverage.json written by MapBuilder (no COLMAP / pycolmap)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from coverage_schema import (
    MapCoverageRecord,
    extract_geodetic_index_fields,
    volumes_include_map_frame,
)
from map_catalog import MapRef


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_coverage_json(map_dir: Path) -> Optional[Dict[str, Any]]:
    path = map_dir / "coverage.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_volumes(raw: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    vols = raw.get("volumes")
    if not isinstance(vols, list):
        return None
    return [v for v in vols if isinstance(v, dict)]


def _updated_at_from_artifact(raw: Dict[str, Any], ingest_ts: str) -> str:
    ca = raw.get("computed_at")
    if ca is not None:
        return str(ca)
    return ingest_ts


def ingest_map(map_ref: MapRef) -> MapCoverageRecord:
    """Build index record from on-disk coverage.json (or missing/invalid state)."""
    ingest_ts = _now_iso()
    base = MapCoverageRecord(
        map_id=map_ref.map_id,
        coverage_status="missing",
        updated_at=ingest_ts,
    )
    raw = load_coverage_json(map_ref.path)
    if raw is None:
        return base

    updated_at = _updated_at_from_artifact(raw, ingest_ts)

    file_map_id = raw.get("map_id")
    if file_map_id is not None and str(file_map_id) != map_ref.map_id:
        return base.model_copy(
            update={
                "coverage_status": "invalid",
                "ingest_error": f"coverage.json map_id {file_map_id!r} != {map_ref.map_id!r}",
                "updated_at": updated_at,
            }
        )

    volumes = _normalize_volumes(raw)
    if volumes is None or not volumes_include_map_frame(raw, map_ref.map_id):
        return base.model_copy(
            update={
                "coverage_status": "invalid",
                "ingest_error": "volumes must include map COLMAP frame with aabb.min_xyz/max_xyz",
                "updated_at": updated_at,
                "volumes": volumes,
            }
        )

    geo_aabb, geo_footprint, geo_query_strategy, geo_err = extract_geodetic_index_fields(raw)
    if geo_err is not None:
        return base.model_copy(
            update={
                "coverage_status": "invalid",
                "ingest_error": geo_err,
                "updated_at": updated_at,
                "volumes": volumes,
            }
        )

    try:
        record = MapCoverageRecord(
            map_id=map_ref.map_id,
            coverage_status="ok",
            geo_aabb=geo_aabb,
            geo_footprint=geo_footprint,
            geo_query_strategy=geo_query_strategy,
            volumes=volumes,
            model_signature=str(raw["model_signature"]) if raw.get("model_signature") is not None else None,
            localization_model_signature=str(raw["localization_model_signature"])
            if raw.get("localization_model_signature") is not None
            else None,
            coverage_schema_version=int(raw["coverage_schema_version"])
            if raw.get("coverage_schema_version") is not None
            else None,
            updated_at=updated_at,
        )
        MapCoverageRecord.model_validate(record.model_dump())
        return record
    except Exception as ex:
        return base.model_copy(
            update={
                "coverage_status": "invalid",
                "ingest_error": str(ex),
                "updated_at": updated_at,
                "volumes": volumes,
            }
        )
