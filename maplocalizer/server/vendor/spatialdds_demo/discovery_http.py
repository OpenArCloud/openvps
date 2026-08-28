"""
Shared semantics for the SpatialDDS 1.7 HTTP discovery binding (Layer 1.5).

Both HTTP servers in this repo answer `/.well-known/spatialdds/search` from
this module, so there is exactly one implementation of matching, filtering,
pagination and manifest assembly:

  * ``ar_demo/http_binding.py`` — conformance harness over an in-memory
    registry fed by its demo-local ``register`` endpoint.
  * ``bridges/web_bridge/server.py`` — gateway over the live announce cache
    fed by the DDS bus.

They differ only in where their :class:`ServiceRecord` list comes from. If a
change here needs an if-branch on which server is calling, the split is in the
wrong place.

Nothing here imports FastAPI, CycloneDDS, or either server's registry.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spatialdds_validation import SpatialDDSValidator

MANIFEST_PROFILE = "spatial.manifest/1.7"

# Source of a record. Not the service *kind* (VPS / MAPPING / ...), which
# lives in the payload.
SOURCE_ANNOUNCE = "announce"
SOURCE_MANIFEST = "manifest"


class DiscoveryError(Exception):
    """A caller-facing failure, carrying the HTTP status it maps to."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class ServiceRecord:
    """
    One discoverable service, in the neutral shape both servers can produce.

    ``payload`` is either a discovery ``Announce`` (source=announce) or a
    service manifest document (source=manifest). ``coverage`` and
    ``coverage_frame_ref`` are hoisted out so matching never has to care which.
    """

    service_id: str
    payload: Dict[str, Any]
    coverage: List[Dict[str, Any]] = field(default_factory=list)
    coverage_frame_ref: Optional[Dict[str, Any]] = None
    source: str = SOURCE_ANNOUNCE

    @property
    def manifest_uri(self) -> str:
        if self.source == SOURCE_MANIFEST:
            return self.payload.get("id", "") or ""
        return self.payload.get("manifest_uri", "") or ""


# A hook the gateway uses to serve an authored manifest instead of a
# synthesized one. Returns the document, or None to fall through.
ManifestProvider = Callable[[ServiceRecord], Optional[Dict[str, Any]]]


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------

# Geometry members and the flag that governs each, for the edge normalization
# below.
_PRESENCE_FLAGS = (
    ("bbox", "has_bbox"),
    ("aabb", "has_aabb"),
    ("crs", "has_crs"),
    ("frame_ref", "has_frame_ref"),
)


def _normalize_element(element: Dict[str, Any]) -> Dict[str, Any]:
    """
    One CoverageElement as the HTTP binding's own examples write it.

    The IDL models optionality as a `has_x` flag beside a value, and that is
    what rides the bus. The spec's §3.3.0 request examples are hand-written
    JSON that simply omits the flags — `{"crs": "EPSG:4326", "bbox": [...]}` is
    the binding's own worked example — so a server that insists on the flags
    rejects the documented request. The flag is inferred only when its key is
    *absent*; an explicit `false` still means "ignore this member", which is
    the rule §3.3.4 states and the reason the flags exist.

    Circle has no entry above: `circle_center` is a fixed-length array that is
    present-but-zero on every element that came off the bus, so a present key
    says nothing. `has_circle` must be explicit.
    """
    if not isinstance(element, dict):
        raise DiscoveryError("Each coverage element must be a JSON object")
    out = dict(element)
    for member, flag in _PRESENCE_FLAGS:
        if flag not in out and out.get(member) not in (None, "", [], {}):
            out[flag] = True
    return out


def normalize_search_request(query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate a search body and return it in the shape matching works on.

    Rejections raise :class:`DiscoveryError`, which carries the HTTP status.

    Hard cutover: 1.7 deleted ``CoverageQuery.expr`` along with Appendix F.X,
    so a body carrying it is rejected rather than silently answered with the
    filter the caller believes is being applied.

    Two accommodations for the HTTP binding's request table (§3.3.0), which is
    not quite the on-bus ``CoverageQuery`` struct:

    * ``geohash`` is a top-level shorthand — "the server expands the geohash to
      its bounding box and treats it as an additional coverage element". A body
      of ``{"geohash": "9q8yy"}`` alone is the binding's minimal example, and
      the GET convenience form is *defined* as equivalent to it, so it has to
      be answerable.
    * ``coverage_frame_ref`` is not in the request table at all and appears in
      none of its examples, so a conformant client will not send one. Absent,
      the query is read as earth-fixed, which is what §3.3.4 says an element
      with no frame means.
    """
    if not isinstance(query, dict):
        raise DiscoveryError("Request body must be a JSON object")

    if "expr" in query:
        raise DiscoveryError(
            "CoverageQuery.expr was removed in SpatialDDS 1.7; use the "
            "structured 'filter' (CoverageFilter) instead"
        )

    raw_coverage = query.get("coverage")
    if raw_coverage is not None and not isinstance(raw_coverage, list):
        raise DiscoveryError("coverage must be an array of CoverageElement")
    coverage = [_normalize_element(e) for e in (raw_coverage or [])]

    frame_ref = query.get("coverage_frame_ref")

    geohash = query.get("geohash")
    if geohash:
        if not isinstance(geohash, str):
            raise DiscoveryError("geohash must be a string")
        west, south, east, north = geohash_bounds(geohash)
        geohash_frame, element = _earth_fixed_bbox(west, south, east, north)
        # An *additional* element, per §3.3.0 — a geohash alongside a coverage
        # block widens the query rather than replacing it.
        coverage.append(element)
        if frame_ref is None:
            frame_ref = geohash_frame

    if not coverage:
        raise DiscoveryError(
            "search requires coverage[] or a geohash (§3.3.0: 400 on missing "
            "coverage)"
        )

    if frame_ref is None:
        frame_ref = _earth_fixed_frame_ref()

    try:
        SpatialDDSValidator.validate_frame_ref(frame_ref)
        SpatialDDSValidator.validate_coverage(coverage, frame_ref)
    except Exception as exc:
        raise DiscoveryError(f"Invalid coverage: {exc}") from exc

    normalized = dict(query)
    normalized["coverage"] = coverage
    normalized["coverage_frame_ref"] = frame_ref
    return normalized


def validate_search_request(query: Dict[str, Any]) -> None:
    """Validate only, for callers that do not want the normalized body."""
    normalize_search_request(query)


def _earth_fixed_frame_ref() -> Dict[str, Any]:
    """The frame an element with no declared frame is in (§3.3.4)."""
    frame_ref, _ = _earth_fixed_bbox(0.0, 0.0, 0.0, 0.0)
    return frame_ref


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

# The §3.3.4 coverage model, as one predicate.
#
# Every coverage consumer in the repo — HTTP search, the on-bus CoverageQuery
# responder, the catalogue server — comes through here, via
# `SpatialDDSValidator.check_coverage_intersection` for the two that predate
# this module. Matching on the bus and matching over HTTP must agree, and the
# only way to be sure of that is for there to be one of them.
#
# It used to consider `bbox` alone. `aabb` has been in CoverageElement since
# 1.4 and `circle` arrived in 1.7's findings-batch-2 revision, so a service
# that declared either — which is every service in the multi-operator fusion
# demo, whose footprints are circles — was invisible to every coverage query
# regardless of where it was.

# Metres per degree of latitude on WGS84, near enough for a bounding-box
# approximation of a circle. §3.3.4: "For intersects evaluation a circle MAY
# be approximated by its bounding box."
_M_PER_DEG_LAT = 111320.0

EARTH_FIXED = "earth-fixed"


def _frame_key(element: Dict[str, Any], default_frame_ref: Optional[Dict[str, Any]]) -> str:
    """
    Which frame an element's numbers are in, as a comparable key.

    §3.3.4: an element uses its own `frame_ref` when `has_frame_ref` is set and
    the announcement's `coverage_frame_ref` otherwise. Geometry in an
    earth-fixed frame is degrees of longitude and latitude; geometry in a local
    frame is metres. Numbers from two different frames are not comparable until
    a transform relates them, which §3.3.4 leaves as a MAY and this predicate
    does not attempt — so they do not intersect here, rather than intersecting
    by numeric coincidence. A local footprint stays invisible to a lon/lat
    query until someone resolves its frame, which is the honest answer.
    """
    frame = element.get("frame_ref") if element.get("has_frame_ref") else default_frame_ref
    fqn = ((frame or {}).get("fqn") or "").strip()
    if not fqn or fqn == EARTH_FIXED or fqn.startswith(EARTH_FIXED + "/"):
        return EARTH_FIXED
    return fqn


def _finite(values: Sequence[Any]) -> bool:
    """§3.3.4: consumers SHALL reject non-finite coordinates."""
    try:
        return all(math.isfinite(float(v)) for v in values)
    except (TypeError, ValueError):
        return False


def _circle_extent(
    center: Sequence[float], radius_m: float, frame: str
) -> Tuple[float, float, float, float]:
    """A circle's bounding box, in the units its frame uses."""
    if frame != EARTH_FIXED:
        # Local frames are metres throughout, so the radius needs no conversion.
        return (center[0] - radius_m, center[1] - radius_m,
                center[0] + radius_m, center[1] + radius_m)
    lon, lat = float(center[0]), float(center[1])
    d_lat = radius_m / _M_PER_DEG_LAT
    # Longitude degrees shrink towards the poles. Clamped so a footprint at a
    # pole widens to the whole band instead of dividing by zero.
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    d_lon = min(radius_m / (_M_PER_DEG_LAT * cos_lat), 180.0)
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def coverage_extents(
    coverage: Sequence[Dict[str, Any]],
    frame_ref: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, float, float, float, float]]:
    """
    Every 2D extent a coverage block declares, as `(frame, w, s, e, n)`.

    §3.3.4: "consumers SHOULD treat the union of all regions as the effective
    coverage" — so an element contributes one extent per geometry it carries,
    and an element carrying both a circle and its bounding aabb (which is what
    the fusion demo publishes, so that aabb-only consumers still see something)
    contributes both. Extents are only ever tested for overlap, so a redundant
    one costs nothing.
    """
    extents: List[Tuple[str, float, float, float, float]] = []
    for element in coverage or []:
        if not isinstance(element, dict):
            continue
        frame = _frame_key(element, frame_ref)

        if element.get("has_bbox"):
            bbox = element.get("bbox") or []
            if len(bbox) >= 4 and _finite(bbox[:4]):
                w, s, e, n = (float(v) for v in bbox[:4])
                extents.append((frame, min(w, e), min(s, n), max(w, e), max(s, n)))

        if element.get("has_aabb"):
            aabb = element.get("aabb") or {}
            lo = aabb.get("min_xyz") or []
            hi = aabb.get("max_xyz") or []
            if len(lo) >= 2 and len(hi) >= 2 and _finite([*lo[:2], *hi[:2]]):
                extents.append((frame,
                                min(float(lo[0]), float(hi[0])),
                                min(float(lo[1]), float(hi[1])),
                                max(float(lo[0]), float(hi[0])),
                                max(float(lo[1]), float(hi[1]))))

        if element.get("has_circle"):
            center = element.get("circle_center") or []
            radius = element.get("circle_radius_m")
            if len(center) >= 2 and _finite([*center[:2], radius]) and float(radius) >= 0.0:
                extents.append((frame, *_circle_extent(center, float(radius), frame)))

    return extents


def _extents_overlap(
    a: Tuple[str, float, float, float, float],
    b: Tuple[str, float, float, float, float],
) -> bool:
    if a[0] != b[0]:
        return False                       # different frames: not comparable
    _, w1, s1, e1, n1 = a
    _, w2, s2, e2, n2 = b
    if e1 < w2 or e2 < w1:
        return False
    if n1 < s2 or n2 < s1:
        return False
    return True                            # touching edges count as overlapping


def coverage_intersects(
    query_coverage: Sequence[Dict[str, Any]],
    record_coverage: Sequence[Dict[str, Any]],
    *,
    query_frame_ref: Optional[Dict[str, Any]] = None,
    record_frame_ref: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Does a query's coverage meet a record's? §3.3.4, bbox / aabb / circle.

    Frame refs are optional because the two older call sites (the on-bus
    responder and the catalogue server) never had them to pass; absent, an
    element without its own `frame_ref` is read as earth-fixed, which is what
    every announcement in this repo that omits one means.
    """
    # `global` is the explicit worldwide toggle, on either side: a worldwide
    # service answers any query, and a worldwide query reaches any service.
    for side in (record_coverage or [], query_coverage or []):
        if any(isinstance(e, dict) and e.get("global") for e in side):
            return True

    query_extents = coverage_extents(query_coverage, query_frame_ref)
    record_extents = coverage_extents(record_coverage, record_frame_ref)
    return any(_extents_overlap(q, r) for q in query_extents for r in record_extents)


def matches_kind(kinds: Sequence[str], record: ServiceRecord) -> bool:
    """Top-level `kind` filter from the spec's HTTP binding. Empty = match all."""
    if not kinds:
        return True
    payload = record.payload
    if record.source == SOURCE_MANIFEST:
        value = (payload.get("service") or {}).get("kind")
    else:
        value = payload.get("kind")
    return value in set(kinds)


def matches_filter(filter_obj: Dict[str, Any], record: ServiceRecord) -> bool:
    """
    Evaluate a `CoverageFilter` (type_in / qos_profile_in / module_id_in).

    Empty arrays mean "match all", per the spec. Unset arrays likewise.
    """
    if not isinstance(filter_obj, dict):
        return True
    type_in = filter_obj.get("type_in") or []
    qos_in = filter_obj.get("qos_profile_in") or []
    module_id_in = filter_obj.get("module_id_in") or []

    payload = record.payload
    topics = payload.get("topics") or []
    if not topics and isinstance(payload.get("service"), dict):
        topics = payload["service"].get("topics") or []

    topic_match = True
    if type_in or qos_in:
        topic_match = False
        for topic in topics:
            if type_in and topic.get("type") not in type_in:
                continue
            if qos_in and topic.get("qos_profile") not in qos_in:
                continue
            topic_match = True
            break

    module_match = True
    if module_id_in:
        module_match = False
        caps = payload.get("caps") or {}
        for profile in (caps.get("supported_profiles") or []):
            name = profile.get("name")
            major = profile.get("major")
            max_minor = profile.get("max_minor")
            if not name or major is None or max_minor is None:
                continue
            # 1.7: ProfileSupport.name already carries the module family
            # ("spatial.core"), so it is not re-prefixed here — doing so would
            # produce "spatial.spatial.core/1.7".
            if f"{name}/{int(major)}.{int(max_minor)}" in module_id_in:
                module_match = True
                break

    return topic_match and module_match


# --------------------------------------------------------------------------
# Manifest assembly
# --------------------------------------------------------------------------

def coverage_block(record: ServiceRecord) -> Optional[Dict[str, Any]]:
    """
    Build a manifest `coverage` block (spec 8.1 / 3.3.4) from a record.

    Follows the spec's own manifest idiom: canonical `frame_ref` plus the
    primary element's geometry inlined, and an `elements` array when there is
    more than one element, or when the primary carries a per-element frame
    override that must not be hoisted onto the canonical frame.
    """
    elements = record.coverage or []
    frame_ref = record.coverage_frame_ref
    if not elements and not frame_ref:
        return None

    block: Dict[str, Any] = {}
    if frame_ref:
        block["frame_ref"] = frame_ref

    primary = elements[0] if elements else None
    primary_overrides_frame = bool(primary and primary.get("has_frame_ref"))
    if primary and not primary_overrides_frame:
        block.update(
            {k: v for k, v in primary.items() if k not in ("has_frame_ref", "frame_ref")}
        )
    if len(elements) > 1 or primary_overrides_frame:
        block["elements"] = elements

    block.setdefault("global", any(bool(e.get("global")) for e in elements))
    return block


def to_service_manifest(
    record: ServiceRecord,
    manifest_provider: Optional[ManifestProvider] = None,
) -> Dict[str, Any]:
    """
    Produce the service manifest document (spec 8.1 envelope + 8.2.3 service
    block) that the HTTP binding returns for a record.

    Serve-or-synthesize, in order:

      1. an authored document from ``manifest_provider``, served verbatim;
      2. the record's own payload, when it already is a manifest;
      3. a manifest synthesized from the announce — fields the announce
         provides are carried across, and optional manifest fields it cannot
         supply are omitted rather than invented.
    """
    if manifest_provider is not None:
        served = manifest_provider(record)
        if served:
            return served

    if record.source == SOURCE_MANIFEST:
        return record.payload

    payload = record.payload
    service: Dict[str, Any] = {
        "service_id": payload.get("service_id", ""),
        "kind": payload.get("kind", "OTHER"),
    }
    for name in ("name", "org", "version"):
        if payload.get(name):
            service[name] = payload[name]
    if payload.get("topics"):
        service["topics"] = payload["topics"]

    manifest: Dict[str, Any] = {
        "id": payload.get("manifest_uri", ""),
        "profile": MANIFEST_PROFILE,
        "rtype": "service",
        "service": service,
    }
    if payload.get("caps"):
        manifest["caps"] = payload["caps"]
    coverage = coverage_block(record)
    if coverage:
        manifest["coverage"] = coverage
    if payload.get("transforms"):
        manifest["transforms"] = payload["transforms"]
    if payload.get("stamp"):
        manifest["stamp"] = payload["stamp"]
    if payload.get("ttl_sec") is not None:
        manifest["ttl_sec"] = payload["ttl_sec"]
    return manifest


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def _parse_page_token(token: str) -> int:
    if not token:
        return 0
    if token.startswith("o="):
        try:
            return max(0, int(token.split("=", 1)[1]))
        except ValueError:
            return 0
    return 0


def search(
    records: Sequence[ServiceRecord],
    query: Dict[str, Any],
    manifest_provider: Optional[ManifestProvider] = None,
) -> Dict[str, Any]:
    """
    Answer a search request, returning the spec's HTTP-binding envelope:
    ``{"results": [<manifest>, ...], "next_page_token": "..."}``.

    No ``query_id`` — HTTP correlates request and response itself. The on-bus
    ``CoverageResponse`` keeps ``query_id`` and returns compact
    ``ServiceSummary`` rows instead; that asymmetry is intentional and is
    documented in ``ar_demo/SPEC_COMPLIANCE.md``.

    Results are ordered by ``service_id`` so paging is stable across calls.
    """
    query = normalize_search_request(query)

    coverage_q = query.get("coverage") or []
    has_filter = bool(query.get("has_filter")) or isinstance(query.get("filter"), dict)
    filter_obj = query.get("filter") or {}
    kinds = query.get("kind") or []

    matched: List[ServiceRecord] = []
    seen: set = set()
    for record in records:
        if record.service_id and record.service_id in seen:
            continue
        if not coverage_intersects(
            coverage_q, record.coverage,
            query_frame_ref=query.get("coverage_frame_ref"),
            record_frame_ref=record.coverage_frame_ref,
        ):
            continue
        if not matches_kind(kinds, record):
            continue
        if has_filter and not matches_filter(filter_obj, record):
            continue
        matched.append(record)
        if record.service_id:
            seen.add(record.service_id)

    matched.sort(key=lambda r: r.service_id or "")

    offset = _parse_page_token(str(query.get("page_token") or ""))
    max_results = query.get("max_results")
    if max_results is None:
        limit = None                       # unset: the server's own choice
    else:
        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            raise DiscoveryError("max_results must be an integer")
        if limit < 0:
            raise DiscoveryError("max_results must not be negative")

    # `None` and `0` are different requests: unset means "server-defined",
    # which here is all of them, while an explicit zero asked for none.
    page = matched[offset:] if limit is None else matched[offset: offset + limit]
    next_token = ""
    # `limit > 0`, not just `limit is not None`: a zero-sized page advances the
    # offset by nothing, so offering a token would hand the client a loop.
    if limit is not None and limit > 0 and offset + limit < len(matched):
        next_token = f"o={offset + limit}"

    return {
        "results": [to_service_manifest(r, manifest_provider) for r in page],
        "next_page_token": next_token,
    }


# --------------------------------------------------------------------------
# Geohash shorthand (spec: GET /.well-known/spatialdds/search?geohash=...)
# --------------------------------------------------------------------------

_GEOHASH_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash_bounds(geohash: str) -> Tuple[float, float, float, float]:
    """
    Decode a geohash to its bounding box as ``[west, south, east, north]``.

    Standard base-32 geohash, alternating longitude/latitude bit refinement
    starting with longitude.
    """
    if not geohash:
        raise DiscoveryError("geohash must not be empty")
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    is_lon = True
    for char in geohash.lower():
        idx = _GEOHASH_B32.find(char)
        if idx < 0:
            raise DiscoveryError(f"invalid geohash character: {char!r}")
        for mask in (16, 8, 4, 2, 1):
            if is_lon:
                mid = (lon_lo + lon_hi) / 2
                if idx & mask:
                    lon_lo = mid
                else:
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if idx & mask:
                    lat_lo = mid
                else:
                    lat_hi = mid
            is_lon = not is_lon
    return lon_lo, lat_lo, lon_hi, lat_hi


def query_from_geohash(geohash: str, kinds: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Translate the GET shorthand into the same body the POST path takes."""
    west, south, east, north = geohash_bounds(geohash)
    frame_ref, element = _earth_fixed_bbox(west, south, east, north)
    query: Dict[str, Any] = {
        "coverage": [element],
        "coverage_frame_ref": frame_ref,
    }
    if kinds:
        query["kind"] = list(kinds)
    return query


def _earth_fixed_bbox(west: float, south: float, east: float, north: float):
    from spatialdds_validation import create_coverage_bbox_earth_fixed

    return create_coverage_bbox_earth_fixed(west, south, east, north)


# --------------------------------------------------------------------------
# Bootstrap manifest (spec 5.x)
# --------------------------------------------------------------------------

def bootstrap_manifest() -> Dict[str, Any]:
    """
    The deployment's bootstrap manifest, served at
    ``/.well-known/spatialdds/bootstrap``.

    Driven by the same ``SPATIALDDS_BOOTSTRAP_*`` environment the bus-side
    bootstrap server reads, so the HTTPS and DDS paths agree. 1.7 replaced the
    ``auth`` object and its method enum with an optional ``auth_hint`` string;
    it is omitted unless configured rather than advertising a placeholder.
    """
    peers = [
        peer.strip()
        for peer in os.getenv("SPATIALDDS_BOOTSTRAP_PEERS", "udpv4://127.0.0.1:7400").split(",")
        if peer.strip()
    ]
    manifest: Dict[str, Any] = {
        "spatialdds_bootstrap": "1.7",
        "domain_id": int(os.getenv("SPATIALDDS_BOOTSTRAP_DOMAIN", "1")),
        "initial_peers": peers,
        "discovery_topic": "spatialdds/discovery/announce/v1",
        "site": os.getenv("SPATIALDDS_BOOTSTRAP_SITE", "sf-downtown"),
    }
    manifest_uris = [
        item.strip()
        for item in os.getenv(
            "SPATIALDDS_BOOTSTRAP_MANIFESTS",
            "spatialdds://vps.example.com/zone:sf-downtown/manifest:vps",
        ).split(",")
        if item.strip()
    ]
    if manifest_uris:
        manifest["manifest_uri"] = manifest_uris[0]
    auth_hint = os.getenv("SPATIALDDS_BOOTSTRAP_AUTH_HINT", "")
    if auth_hint:
        manifest["auth_hint"] = auth_hint
    return manifest


# --------------------------------------------------------------------------
# Record construction
# --------------------------------------------------------------------------

def record_from_announce(announce: Dict[str, Any], *, validate: bool = True) -> ServiceRecord:
    """Build a record from a discovery Announce, validating its coverage."""
    if not isinstance(announce, dict):
        raise DiscoveryError("Announce must be an object")

    if validate:
        for name in ("service_id", "coverage", "coverage_frame_ref", "manifest_uri"):
            if name not in announce:
                raise DiscoveryError(f"Announce missing required '{name}' field")
        try:
            SpatialDDSValidator.validate_frame_ref(announce["coverage_frame_ref"])
            SpatialDDSValidator.validate_coverage(
                announce["coverage"], announce["coverage_frame_ref"]
            )
        except Exception as exc:
            raise DiscoveryError(str(exc)) from exc

    announce.setdefault("stamp", SpatialDDSValidator.now_time())
    announce.setdefault("ttl_sec", 300)

    return ServiceRecord(
        service_id=announce.get("service_id", ""),
        payload=announce,
        coverage=announce.get("coverage") or [],
        coverage_frame_ref=announce.get("coverage_frame_ref"),
        source=SOURCE_ANNOUNCE,
    )


def record_from_manifest(manifest: Dict[str, Any]) -> ServiceRecord:
    """
    Build a record from a service manifest document.

    Hard cutover: `@`-form profiles and pre-1.7 minors are rejected outright.
    """
    SpatialDDSValidator.validate_manifest_profile(manifest.get("profile", ""))

    service = manifest.get("service")
    if not isinstance(service, dict) or not service.get("service_id"):
        raise DiscoveryError("Service manifest missing service.service_id")

    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        raise DiscoveryError("Service manifest missing coverage object")

    coverage_frame_ref = coverage.get("frame_ref")
    if not coverage_frame_ref:
        raise DiscoveryError("Service manifest coverage.frame_ref is required")

    element = dict(coverage)
    element.pop("frame_ref", None)
    element.pop("elements", None)
    element["has_frame_ref"] = False

    try:
        SpatialDDSValidator.validate_frame_ref(coverage_frame_ref)
        SpatialDDSValidator.validate_coverage([element], coverage_frame_ref)
    except Exception as exc:
        raise DiscoveryError(str(exc)) from exc

    manifest.setdefault("stamp", SpatialDDSValidator.now_time())
    manifest.setdefault("ttl_sec", 300)

    elements = coverage.get("elements") or [element]
    return ServiceRecord(
        service_id=service["service_id"],
        payload=manifest,
        coverage=elements,
        coverage_frame_ref=coverage_frame_ref,
        source=SOURCE_MANIFEST,
    )
