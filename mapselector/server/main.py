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
    localize_timeout_s: float = Field(
        default=600.0,
        validation_alias=AliasChoices("MAPSELECTOR_LOCALIZE_TIMEOUT_S"),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_settings_cache: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache


def _cluster_http_client(**kwargs: Any) -> httpx.AsyncClient:
    """In-docker calls only; ignore host HTTP(S)_PROXY so names like maplocalizer resolve on the compose network."""
    return httpx.AsyncClient(trust_env=False, **kwargs)


async def _proxy_localizer_get(path: str, *, timeout: float = 10.0) -> Any:
    cfg = get_settings()
    url = f"{cfg.localizer_url.rstrip('/')}{path}"
    try:
        async with _cluster_http_client(timeout=timeout) as client:
            r = await client.get(url)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("localizer GET %s failed: %s", path, exc)
        raise HTTPException(status_code=502, detail="MapLocalizer unreachable") from exc
    return r.json()


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
async def health_bridge():
    """Proxy MapLocalizer health (loaded maps, worker id) for legacy public-port probes."""
    return await _proxy_localizer_get("/health")


@app.get("/gpu_info")
async def gpu_info_bridge():
    """Proxy MapLocalizer GPU inventory for legacy public-port probes."""
    return await _proxy_localizer_get("/gpu_info")


@app.get("/ready")
def ready():
    return {"ready": True, "service": "mapselector"}


@app.get("/current_map_id")
async def current_map_id_bridge():
    """Proxy MapLocalizer loaded-map id (legacy clients used this on the public GeoPose port)."""
    return await _proxy_localizer_get("/current_map_id")


async def _fetch_registry_candidates(client: httpx.AsyncClient, q: GnssQuery) -> Dict[str, Any]:
    cfg = get_settings()
    params: Dict[str, Any] = {"lat": q.lat, "lon": q.lon, "radius_m": q.radius_m}
    if q.alt is not None and q.alt_radius_m is not None:
        params["alt"] = q.alt
        params["alt_radius_m"] = q.alt_radius_m
    url = f"{cfg.mapregistry_url.rstrip('/')}/maps/query"
    try:
        r = await client.get(url, params=params, timeout=30.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("mapregistry GET /maps/query failed: %s", exc)
        raise HTTPException(status_code=502, detail="MapRegistry unreachable") from exc
    return r.json()


async def _fetch_current_map_id(client: httpx.AsyncClient) -> Optional[str]:
    cfg = get_settings()
    try:
        r = await client.get(f"{cfg.localizer_url.rstrip('/')}/current_map_id", timeout=10.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("maplocalizer GET /current_map_id failed: %s", exc)
        raise HTTPException(status_code=502, detail="MapLocalizer unreachable") from exc
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
        logger.info(
            "map resolve via registry lat=%.6f lon=%.6f radius_m=%.1f",
            q.lat,
            q.lon,
            q.radius_m,
        )
        data = await _fetch_registry_candidates(client, q)
        limit = kMultiMapMaxNumCandidates if kEnableMultiMapLocalization else 1
        ids = candidate_map_ids(data, limit)
        if ids:
            return MapResolution(map_ids=ids)
        raise HTTPException(status_code=404, detail="No map coverage intersects coarse location")

    logger.info("map resolve via loaded map (no location hint)")
    map_id = await _fetch_current_map_id(client)
    if not map_id:
        raise HTTPException(
            status_code=404,
            detail=_localization_failed_message(body),
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
    try:
        r = await client.post(url, headers=headers, content=json.dumps(body).encode("utf-8"))
    except httpx.HTTPError as exc:
        logger.warning("maplocalizer POST /localize/geopose failed: %s", exc)
        raise HTTPException(status_code=502, detail="MapLocalizer unreachable") from exc
    media = r.headers.get("content-type") or "application/json"
    return r.status_code, r.content, media


def _gpp_error_response(message: str, status_code: int) -> Response:
    return Response(
        content=json.dumps({"ERROR": message}).encode("utf-8"),
        status_code=status_code,
        media_type="application/json",
    )


def _localization_failed_message(body: Dict[str, Any]) -> str:
    """Same ERROR text MapLocalizer uses when localization does not succeed."""
    req_id = body.get("id", "")
    return f"Could not localize request {req_id}"


@app.post("/localize/geopose")
async def localize_geopose(request: Request):
    """Resolve map from coarse GNSS + registry; proxy GeoPose POST to maplocalizer."""
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("GeoPose body is not valid JSON: %s", exc)
        return _gpp_error_response("Request body must be valid JSON", 400)
    if not isinstance(body, dict):
        return _gpp_error_response("GeoPose request must be a JSON object", 400)

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

    timeout = get_settings().localize_timeout_s
    async with _cluster_http_client(timeout=timeout) as client:
        try:
            resolution = await _resolve_map_resolution(client, body)
        except HTTPException as exc:
            msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            logger.warning("map resolution failed status=%s detail=%s", exc.status_code, msg)
            return _gpp_error_response(msg, exc.status_code)
        except (TypeError, ValueError) as exc:
            logger.exception("invalid location fields in GeoPose body")
            return _gpp_error_response(f"Invalid location hint in request: {exc}", 400)

        use_map_header = not resolution.used_loaded_map_fallback

        for map_id in resolution.map_ids:
            tried.append(map_id)
            try:
                status, content, media = await _proxy_localize(
                    client,
                    map_id,
                    body,
                    forward_headers,
                    use_map_header=use_map_header,
                )
            except HTTPException as exc:
                msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                logger.warning("proxy localize failed map_id=%s detail=%s", map_id, msg)
                return _gpp_error_response(msg, exc.status_code)
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