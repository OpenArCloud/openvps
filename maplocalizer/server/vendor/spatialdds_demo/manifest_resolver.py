import json
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, quote
from urllib.request import urlopen

_CACHE: Dict[str, Tuple[float, Optional[Dict], Dict[str, str]]] = {}


def _cache_get(manifest_uri: str) -> Optional[Tuple[Optional[Dict], Dict[str, str]]]:
    cached = _CACHE.get(manifest_uri)
    if not cached:
        return None
    expiry, data, status = cached
    if time.time() > expiry:
        _CACHE.pop(manifest_uri, None)
        return None
    return data, status


def _cache_put(manifest_uri: str, data: Optional[Dict], status: Dict[str, str], ttl_sec: int) -> None:
    _CACHE[manifest_uri] = (time.time() + ttl_sec, data, status)


def _resolve_local(manifest_uri: str) -> Tuple[Optional[Dict], Dict[str, str]]:
    # Mapping: spatialdds://vps.example.com/zone:sf-downtown/manifest:vps
    # -> manifests/v1.7/vps_sf_downtown.json (resolved relative to repo root,
    # not cwd, so callers can run from any directory)
    repo_root = Path(__file__).resolve().parent.parent
    mapping = {
        "spatialdds://vps.example.com/zone:sf-downtown/manifest:vps": (
            repo_root / "manifests/v1.7/vps_sf_downtown.json"
        )
    }
    local_path = mapping.get(manifest_uri)
    if not local_path:
        return None, {"mode": "LOCAL_MISSING", "path": ""}

    with open(local_path, "r", encoding="utf-8") as handle:
        return json.load(handle), {"mode": "LOCAL", "path": str(local_path)}


# Resolver metadata is per-authority and cheap to reuse across manifests.
_RESOLVER_CACHE: Dict[str, Tuple[float, Optional[Dict]]] = {}

# 1.7 consolidated the well-known namespace to a single RFC 8615
# registration: /.well-known/spatialdds/{bootstrap,resolver,search}. Direct
# manifest fetches therefore live one level down, under .../manifests/, so a
# manifest path can never shadow one of the three reserved names.
WELL_KNOWN_BASE = "/.well-known/spatialdds"
WELL_KNOWN_RESOLVER = f"{WELL_KNOWN_BASE}/resolver"
WELL_KNOWN_MANIFESTS = f"{WELL_KNOWN_BASE}/manifests"


def _resolver_metadata(authority: str) -> Optional[Dict]:
    """Fetch (and cache) https://{authority}/.well-known/spatialdds/resolver."""
    cached = _RESOLVER_CACHE.get(authority)
    if cached and time.time() <= cached[0]:
        return cached[1]

    url = f"https://{authority}{WELL_KNOWN_RESOLVER}"
    try:
        with urlopen(url, timeout=5) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except Exception:
        metadata = None

    ttl = 300
    if isinstance(metadata, dict):
        try:
            ttl = int(metadata.get("cache_ttl_sec", ttl) or ttl)
        except (TypeError, ValueError):
            ttl = 300
    else:
        metadata = None
    _RESOLVER_CACHE[authority] = (time.time() + ttl, metadata)
    return metadata


def _resolve_remote(manifest_uri: str) -> Tuple[Optional[Dict], Dict[str, str]]:
    """
    HTTPS resolution per spec 7.5.1 steps 3-4: try the authority's advertised
    resolver first, then fall back to the well-known manifests path.
    """
    parsed = urlparse(manifest_uri)
    if parsed.scheme != "spatialdds":
        return None, {"mode": "HTTPS_UNSUPPORTED", "path": ""}
    authority = parsed.netloc
    path = parsed.path.lstrip("/")
    encoded_path = quote(path, safe="")

    # 3. Advertised resolver — GET {https_base}?uri={urlencoded SpatialURI}
    metadata = _resolver_metadata(authority)
    https_base = (metadata or {}).get("https_base")
    if https_base:
        url = f"{https_base}?uri={quote(manifest_uri, safe='')}"
        try:
            with urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data, {"mode": "HTTPS_RESOLVER", "path": url}
        except Exception:
            pass  # fall through to the required HTTPS baseline

    # 4. HTTPS fallback
    url = f"https://{authority}{WELL_KNOWN_MANIFESTS}/{encoded_path}.json"
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8")), {"mode": "HTTPS", "path": url}


def resolve_manifest(manifest_uri: str, ttl_sec: int = 300) -> Tuple[Optional[Dict], Dict[str, str]]:
    """
    Resolve a SpatialDDS URI to a manifest, following spec 7.5.1 order:
    local cache -> advertised resolver -> HTTPS fallback -> failure.

    The demo short-circuits with a bundled local mapping so the AR flow runs
    offline; HTTPS is opt-in via ALLOW_HTTPS=1.
    """
    cached = _cache_get(manifest_uri)
    if cached:
        data, status = cached
        return data, {**status, "cached": "1"}

    parsed = urlparse(manifest_uri)
    if parsed.scheme == "https":
        if os.getenv("ALLOW_HTTPS", "0") != "1":
            status = {"mode": "HTTPS_DISABLED", "path": ""}
            _cache_put(manifest_uri, None, status, ttl_sec)
            return None, status
        data, status = _resolve_remote(manifest_uri.replace("https://", "spatialdds://", 1))
        _cache_put(manifest_uri, data, status, ttl_sec)
        return data, status

    if parsed.scheme != "spatialdds":
        status = {"mode": "UNSUPPORTED_SCHEME", "path": ""}
        _cache_put(manifest_uri, None, status, ttl_sec)
        return None, status

    data, status = _resolve_local(manifest_uri)
    _cache_put(manifest_uri, data, status, ttl_sec)
    return data, status
