# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from map_catalog import enumerate_hloc_maps, find_duplicate_map_ids
from ingest import ingest_map
from coverage_schema import MapCoverageRecord, RegistryIndex
from geo_query import rank_distance_m, record_intersects_query
from registry_store import load_index, save_index, upsert_record


class Settings(BaseSettings):
    uploads_dir: str = "/uploads"
    registry_index_path: str = "/uploads/map_registry.json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


def get_settings() -> Settings:
    return Settings()


def _run_full_rescan() -> dict:
    settings = get_settings()
    uploads_root = Path(settings.uploads_dir)
    idx_path = Path(settings.registry_index_path)
    idx = load_index(idx_path)
    errors = []
    for mid, refs in find_duplicate_map_ids(uploads_root):
        paths = ", ".join(f"{r.dataset_id}:{r.path}" for r in refs)
        errors.append(
            {
                "map_id": mid,
                "error": f"duplicate global map_id across datasets ({paths}); index keeps last scan order entry",
            }
        )
    new_maps: dict[str, MapCoverageRecord] = {}
    for map_ref in enumerate_hloc_maps(uploads_root).values():
        try:
            record = ingest_map(map_ref)
            new_maps[record.map_id] = record
            if record.coverage_status == "invalid" and record.ingest_error:
                errors.append({"map_id": map_ref.map_id, "error": record.ingest_error})
        except Exception as e:
            errors.append({"map_id": map_ref.map_id, "error": str(e)})
    idx.maps = new_maps
    save_index(idx_path, idx)
    return {"status": "ok", "map_count": len(idx.maps), "errors": errors}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_full_rescan()
    yield


app = FastAPI(title="OpenVPS Map Coverage Registry", version="2.0.0", lifespan=lifespan)


class ReloadBody(BaseModel):
    dataset_id: str
    map_id: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "mapregistry"}


@app.get("/ready")
def ready():
    return {"ready": True}


@app.get("/maps")
def list_maps():
    settings = get_settings()
    idx_path = Path(settings.registry_index_path)
    idx = load_index(idx_path)
    return {"maps": [m.model_dump(exclude_none=True) for m in idx.maps.values()]}


@app.post("/internal/reload")
def internal_reload(body: ReloadBody):
    settings = get_settings()
    uploads_root = Path(settings.uploads_dir)
    catalog = enumerate_hloc_maps(uploads_root)
    key = body.map_id
    if key not in catalog:
        raise HTTPException(status_code=404, detail=f"Unknown map_id {body.map_id}")
    map_ref = catalog[key]
    if map_ref.dataset_id != body.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id does not match uploads layout")
    record = ingest_map(map_ref)
    upsert_record(Path(settings.registry_index_path), record)
    return {"status": "ok", "coverage": record.model_dump(exclude_none=True)}


@app.post("/internal/rescan")
def internal_rescan():
    return _run_full_rescan()


@app.get("/maps/query")
def maps_query(
    lat: float = Query(..., description="Query latitude (WGS84)"),
    lon: float = Query(..., description="Query longitude (WGS84)"),
    radius_m: float = Query(50.0, ge=1.0, description="Horizontal uncertainty (~GNSS accuracy), meters"),
    alt: float | None = Query(None, description="Optional query altitude (WGS84 ellipsoidal height)"),
    alt_radius_m: float | None = Query(None, ge=0.0, description="Optional vertical uncertainty, meters"),
):
    """Rank geo-aligned maps intersecting coarse GNSS uncertainty (see geo_query)."""
    settings = get_settings()
    idx_path = Path(settings.registry_index_path)
    idx = load_index(idx_path)

    ranked = []
    for mid, rec in idx.maps.items():
        if not rec.eligible_for_geo_query():
            continue
        if not record_intersects_query(rec, lat, lon, radius_m, alt, alt_radius_m):
            continue
        dist_m = rank_distance_m(rec, lat, lon)
        ranked.append(
            {
                "map_id": mid,
                "score": -dist_m,
                "coverage": rec.model_dump(exclude_none=True),
            }
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"candidates": ranked}
