# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""GeoPose gateway: selects map via registry + coarse GNSS, forwards to maplocalizer."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from selection import (
    GnssQuery,
    candidate_map_ids,
    extract_location_query,
    localization_attempt_success,
    should_try_next_map,
)

logger = logging.getLogger(__name__)

# We search the single top candidate only;
# We leave the multi-map localization for future work.
kEnableMultiMapLocalization = False
kMultiMapMaxNumCandidates = 1


@dataclass(frozen=True)
class MapResolution:
    map_ids: List[str]
    used_loaded_map_fallback: bool = False


class Settings(BaseSettings):
    mapregistry_url: str = Field(
        default="http://mapregistry:8101",
        validation_alias=AliasChoices("MAPREGISTRY_URL"),
    )
    localizer_url: str = Field(
        default="http://maplocalizer:8000",
        validation_alias=AliasChoices("MAPLOCALIZER_URL"),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_settings_cache: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache


app = FastAPI(title="OpenVPS MapSelector", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {
        "STATUS": "OpenVPS MapSelector is running. POST /localize/geopose for GeoPose (GPP v2.0)",
        "service": "mapselector",
    }


@app.get("/localize/geopose")
async def localize_ping():
    """Liveness check (GET); localization uses POST with a GeoPoseRequest body."""
    return {"STATUS": "GeoPose server is running", "service": "mapselector"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "mapselector"}


@app.get("/ready")
def ready():
    return {"ready": True, "service": "mapselector"}


@app.get("/current_map_id")
async def current_map_id_bridge():
    """Proxy MapLocalizer loaded-map id (legacy clients used this on the public GeoPose port)."""
    cfg = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{cfg.localizer_url.rstrip('/')}/current_map_id")
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type") or "application/json",
    )


async def _fetch_registry_candidates(q: GnssQuery) -> Dict[str, Any]:
    cfg = get_settings()
    params: Dict[str, Any] = {"lat": q.lat, "lon": q.lon, "radius_m": q.radius_m}
    if q.alt is not None and q.alt_radius_m is not None:
        params["alt"] = q.alt
        params["alt_radius_m"] = q.alt_radius_m
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{cfg.mapregistry_url.rstrip('/')}/maps/query",
            params=params,
        )
        r.raise_for_status()
        return r.json()


async def _fetch_current_map_id(client: httpx.AsyncClient) -> Optional[str]:
    cfg = get_settings()
    r = await client.get(f"{cfg.localizer_url.rstrip('/')}/current_map_id", timeout=10.0)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return None
    mid = data.get("id")
    if mid is None or (isinstance(mid, str) and not mid.strip()):
        return None
    return str(mid)


async def _resolve_map_resolution(client: httpx.AsyncClient, body: Dict[str, Any]) -> MapResolution:
    """Registry rank when prior GeoPose or GNSS hint is present; else currently loaded map."""
    q = extract_location_query(body)
    if q is not None:
        data = await _fetch_registry_candidates(q)
        limit = kMultiMapMaxNumCandidates if kEnableMultiMapLocalization else 1
        ids = candidate_map_ids(data, limit)
        if ids:
            return MapResolution(map_ids=ids)
        raise HTTPException(status_code=404, detail="No map coverage intersects coarse location")

    map_id = await _fetch_current_map_id(client)
    if not map_id:
        raise HTTPException(
            status_code=500,
            detail="No priorPoses, geolocationReadings, or map loaded in MapLocalizer",
        )
    return MapResolution(map_ids=[map_id], used_loaded_map_fallback=True)


async def _proxy_localize(
    client: httpx.AsyncClient,
    map_id: Optional[str],
    body: Dict[str, Any],
    forward_headers: Dict[str, str],
    *,
    use_map_header: bool,
) -> Tuple[int, bytes, str]:
    cfg = get_settings()
    headers = dict(forward_headers)
    if use_map_header and map_id:
        headers["X-OpenVPS-Map-Id"] = map_id
    url = f"{cfg.localizer_url.rstrip('/')}/localize/geopose"
    r = await client.post(url, headers=headers, content=json.dumps(body).encode("utf-8"))
    media = r.headers.get("content-type") or "application/json"
    return r.status_code, r.content, media


@app.post("/localize/geopose")
async def localize_geopose(request: Request):
    """Resolve map from coarse GNSS + registry; proxy GeoPose POST to maplocalizer."""
    body = await request.json()

    forward_headers: Dict[str, str] = {}
    accept = request.headers.get("accept")
    if accept:
        forward_headers["Accept"] = accept
    ct = request.headers.get("content-type")
    if ct:
        forward_headers["Content-Type"] = ct

    last_status = 404
    last_body = b'{"ERROR": "No map produced localization"}'
    last_media = "application/json"
    tried: List[str] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resolution = await _resolve_map_resolution(client, body)
        except HTTPException as exc:
            msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return Response(
                content=json.dumps({"ERROR": msg}).encode("utf-8"),
                status_code=exc.status_code,
                media_type="application/json",
            )

        use_map_header = not resolution.used_loaded_map_fallback

        for map_id in resolution.map_ids:
            tried.append(map_id)
            status, content, media = await _proxy_localize(
                client,
                map_id,
                body,
                forward_headers,
                use_map_header=use_map_header,
            )
            last_status, last_body, last_media = status, content, media
            if localization_attempt_success(status, content, media):
                logger.info("localization ok map_id=%s tried=%s", map_id, tried)
                resp = Response(content=content, status_code=status, media_type=media)
                if map_id:
                    resp.headers["X-OpenVPS-Map-Id"] = map_id
                resp.headers["X-OpenVPS-Maps-Tried"] = ",".join(tried)
                return resp
            if not kEnableMultiMapLocalization or len(resolution.map_ids) == 1:
                break
            if not should_try_next_map(status, content, media):
                break
            logger.info("localization miss map_id=%s status=%s; trying next", map_id, status)

    resp = Response(content=last_body, status_code=last_status, media_type=last_media)
    if tried:
        resp.headers["X-OpenVPS-Maps-Tried"] = ",".join(tried)
        resp.headers["X-OpenVPS-Map-Id"] = tried[-1]
    return resp