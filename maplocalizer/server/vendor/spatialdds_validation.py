#!/usr/bin/env python3
"""
SpatialDDS v1.7 Validation Utilities
Lightweight helpers for Time/FrameRef/Coverage/GeoPose/ServiceSummary
validation aligned with the 1.7 IDL shapes under idl/v1.7.

1.7 is a hard cutover (pre-adoption instability clause, spec 3.1): the
1.5/1.6 shapes are rejected outright, not tolerated.
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class SpatialDDSValidator:
    """Validator for SpatialDDS v1.7 structures"""

    # spatialdds://<authority>/zone:<zone_id>/<rtype>:<rid>
    SPATIAL_URI_PATTERN = (
        r"^spatialdds://([^/]+)/zone:([^/]+)/([^:]+):(.+)$"
    )

    VALID_CRS = {"EPSG:4979", "EPSG:4326"}
    # 1.7 unifies every module on /1.7 and retires the `name@MAJOR.MINOR`
    # form; `spatial.<profile>/MAJOR.MINOR` is the only identifier syntax.
    MODULE_VERSION_PATTERN = r"^spatial\.[a-z_][a-z0-9_.]*/1\.7$"
    MANIFEST_PROFILE_PATTERN = r"^spatial\.manifest/1\.(\d+)$"
    MANIFEST_MIN_MINOR = 7
    VALID_SERVICE_KINDS = {
        "VPS",
        "MAPPING",
        "RELOCAL",
        "SEMANTICS",
        "STORAGE",
        "CONTENT",
        "ANCHOR_REGISTRY",
        "OTHER",
    }

    @staticmethod
    def now_time() -> Dict[str, int]:
        """Return current time as builtin::Time dict"""
        now = datetime.now(timezone.utc)
        sec = int(now.timestamp())
        nanosec = int((now.timestamp() - sec) * 1_000_000_000)
        return {"sec": sec, "nanosec": nanosec}

    @staticmethod
    def time_from_iso(iso_str: str) -> Dict[str, int]:
        """Convert ISO8601 string to builtin::Time dict"""
        dt = datetime.fromisoformat(
            iso_str.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        sec = int(dt.timestamp())
        nanosec = int((dt.timestamp() - sec) * 1_000_000_000)
        return {"sec": sec, "nanosec": nanosec}

    @staticmethod
    def create_frame_ref(fqn: str, coord_convention: str = "ENU") -> Dict[str, Any]:
        """
        Deterministically create a FrameRef using UUIDv5 so the same fqn
        always yields the same uuid (useful for tests/demos).

        §2.12 adds an axis convention. Every demo here is
        ENU-anchored; callers can override for body-frame or camera-frame
        references.
        """
        return {
            "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, fqn)),
            "fqn": fqn,
            "has_coord_convention": True,
            "coord_convention": coord_convention,
        }

    @classmethod
    def validate_time(cls, t: Dict[str, Any]) -> None:
        """Validate builtin::Time"""
        if not isinstance(t, dict):
            raise ValidationError("Time must be an object")
        if "sec" not in t or "nanosec" not in t:
            raise ValidationError("Time requires 'sec' and 'nanosec'")
        if not isinstance(t["sec"], int) or not isinstance(t["nanosec"], int):
            raise ValidationError("'sec' and 'nanosec' must be integers")
        if t["nanosec"] < 0 or t["nanosec"] >= 1_000_000_000:
            raise ValidationError("nanosec must be in [0, 1e9)")

    @classmethod
    def validate_frame_ref(cls, frame_ref: Dict[str, Any]) -> None:
        """Validate spatial::common::FrameRef"""
        if not isinstance(frame_ref, dict):
            raise ValidationError("FrameRef must be an object")
        if not frame_ref.get("uuid"):
            raise ValidationError("FrameRef.uuid is required")
        if not frame_ref.get("fqn"):
            raise ValidationError("FrameRef.fqn is required")

    @classmethod
    def validate_quaternion_xyzw(
        cls, q: List[float], tolerance: float = 1e-6
    ) -> None:
        """Validate quaternion in [x,y,z,w] GeoPose order"""
        if not q or len(q) != 4:
            raise ValidationError(
                f"Quaternion must have exactly 4 components, got {len(q) if q else 0}"
            )
        x, y, z, w = q
        norm = math.sqrt(x * x + y * y + z * z + w * w)
        if abs(norm - 1.0) > tolerance:
            raise ValidationError(
                f"Quaternion is not unit-norm: ||q||={norm:.6f} (expected 1.0 ± {tolerance})"
            )

    @classmethod
    def normalize_quaternion_xyzw(cls, q: List[float]) -> List[float]:
        """Normalize quaternion and return [x,y,z,w]"""
        cls.validate_quaternion_xyzw(q, tolerance=1e-2)  # allow loose check pre-normalization
        x, y, z, w = q
        norm = math.sqrt(x * x + y * y + z * z + w * w)
        if norm < 1e-9:
            raise ValidationError("Cannot normalize near-zero quaternion")
        return [x / norm, y / norm, z / norm, w / norm]

    @classmethod
    def validate_spatial_uri(cls, uri: str) -> Dict[str, str]:
        """
        Validate SpatialDDS URI format (used for manifests in 1.7)
        """
        import re

        if not uri:
            raise ValidationError("URI cannot be empty")
        match = re.match(cls.SPATIAL_URI_PATTERN, uri)
        if not match:
            raise ValidationError(
                f"Invalid SpatialDDS URI: {uri}\n"
                "Expected spatialdds://<authority>/zone:<zone_id>/<rtype>:<rid>"
            )
        authority, zone_id, rtype, rid = match.groups()
        return {
            "authority": authority,
            "zone_id": zone_id,
            "rtype": rtype,
            "rid": rid,
        }

    @classmethod
    def validate_coverage_element(
        cls,
        element: Dict[str, Any],
        coverage_frame_ref: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Validate discovery::CoverageElement.

        1.7 deleted ``CoverageElement.type``: the geometry kind is derived
        from the presence flags. ``has_bbox`` is the geographic (bbox) form,
        ``has_aabb`` alone is the local volume form, ``has_circle`` is the
        centre-and-radius form added by 1.7's findings-batch-2 revision, and
        none of the three plus ``global: true`` is the global form.
        """
        if "type" in element:
            raise ValidationError(
                "CoverageElement.type was removed in 1.7; derive the geometry "
                "kind from has_bbox / has_aabb / global instead"
            )
        is_volume = bool(element.get("has_aabb")) and not element.get("has_bbox")

        if element.get("has_bbox"):
            bbox = element.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise ValidationError("bbox must be an array [west,south,east,north]")
            if not all(math.isfinite(v) for v in bbox):
                raise ValidationError("bbox values must be finite numbers")
            if coverage_frame_ref and coverage_frame_ref.get("fqn") == "earth-fixed":
                if not element.get("has_crs"):
                    raise ValidationError("earth-fixed bbox requires has_crs=true and crs set")
                crs = element.get("crs")
                if crs not in cls.VALID_CRS:
                    raise ValidationError(f"Invalid CRS '{crs}' (expected one of {sorted(cls.VALID_CRS)})")

        if element.get("has_aabb"):
            aabb = element.get("aabb")
            if not isinstance(aabb, dict):
                raise ValidationError("aabb must be an object with min_xyz/max_xyz")
            if not isinstance(aabb.get("min_xyz"), list) or not isinstance(aabb.get("max_xyz"), list):
                raise ValidationError("aabb.min_xyz and aabb.max_xyz must be arrays")
            if len(aabb["min_xyz"]) != 3 or len(aabb["max_xyz"]) != 3:
                raise ValidationError("aabb vectors must have 3 components each")
            if not all(math.isfinite(v) for v in aabb["min_xyz"] + aabb["max_xyz"]):
                raise ValidationError("aabb values must be finite numbers")
            if is_volume:
                if element.get("has_crs"):
                    raise ValidationError("volume aabb must not set has_crs; use frame_ref instead")
                frame_ref = element.get("frame_ref") if element.get("has_frame_ref") else coverage_frame_ref
                if not frame_ref:
                    raise ValidationError("volume aabb requires frame_ref (or coverage_frame_ref)")
                if frame_ref.get("fqn") == "earth-fixed":
                    min_xyz = aabb["min_xyz"]
                    max_xyz = aabb["max_xyz"]
                    looks_like_lon_lat = (
                        all(abs(v) <= 180.0 for v in (min_xyz[0], max_xyz[0]))
                        and all(abs(v) <= 90.0 for v in (min_xyz[1], max_xyz[1]))
                        and all(abs(v) <= 1000.0 for v in (min_xyz[2], max_xyz[2]))
                    )
                    if looks_like_lon_lat:
                        raise ValidationError(
                            "volume aabb appears to be lon/lat; use meters with a frame_ref"
                        )

        if element.get("has_circle"):
            center = element.get("circle_center")
            radius = element.get("circle_radius_m")
            if not isinstance(center, list) or len(center) != 3:
                raise ValidationError(
                    "circle_center must be an array [x, y, z] "
                    "(lon, lat, alt in earth-fixed frames)"
                )
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in center):
                raise ValidationError("circle_center values must be finite numbers")
            if not isinstance(radius, (int, float)) or not math.isfinite(radius):
                raise ValidationError("circle_radius_m must be a finite number")
            if radius < 0:
                raise ValidationError("circle_radius_m must not be negative")

        if element.get("has_frame_ref"):
            frame_ref = element.get("frame_ref")
            if not frame_ref:
                raise ValidationError("has_frame_ref is true but frame_ref missing")
            cls.validate_frame_ref(frame_ref)

        if not any(element.get(flag) for flag in ("has_bbox", "has_aabb", "has_circle")):
            if not element.get("global"):
                raise ValidationError(
                    "CoverageElement must provide bbox, aabb or circle "
                    "geometry, or set global=true"
                )

    @classmethod
    def validate_geo_pose(cls, geopose: Dict[str, Any]) -> None:
        """
        Validate core::GeoPose.

        1.7 fixed the orientation to the local ENU tangent frame at the
        encoded position and deleted ``frame_kind`` / ``frame_ref``
        (and ``enum GeoFrameKind``). Their presence is a 1.6 payload.
        """
        if not isinstance(geopose, dict):
            raise ValidationError("GeoPose must be an object")
        for field in ("lat_deg", "lon_deg", "alt_m"):
            value = geopose.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValidationError(f"GeoPose.{field} must be a finite number")
        for removed in ("frame_kind", "frame_ref"):
            if removed in geopose:
                raise ValidationError(
                    f"GeoPose.{removed} was removed in 1.7; orientation is "
                    "always the local ENU tangent frame at the encoded position"
                )
        cls.validate_quaternion_xyzw(geopose.get("q"))
        if "stamp" in geopose:
            cls.validate_time(geopose["stamp"])

    @classmethod
    def validate_module_version(cls, version: str) -> None:
        """
        Validate a module/schema version string.

        Hard cutover: 1.7 unifies every module on ``spatial.<profile>/1.7``
        and retires the ``name@MAJOR.MINOR`` form, so ``/1.5``, ``/1.6``
        and every ``@`` form are rejected.
        """
        import re

        if not isinstance(version, str) or not version:
            raise ValidationError("Module version must be a non-empty string")
        if "@" in version:
            raise ValidationError(
                f"Profile identifier '{version}' uses the retired "
                "'name@MAJOR.MINOR' form; 1.7 accepts only "
                "'spatial.<profile>/MAJOR.MINOR'"
            )
        if not re.match(cls.MODULE_VERSION_PATTERN, version):
            raise ValidationError(
                f"Invalid module version '{version}' (expected "
                "'spatial.<profile>/1.7'; all modules version together in 1.7)"
            )

    @classmethod
    def validate_manifest_profile(cls, profile: str) -> None:
        """Validate a manifest ``profile`` string (spec 8.1)."""
        import re

        if not isinstance(profile, str) or not profile:
            raise ValidationError("Manifest profile must be a non-empty string")
        if "@" in profile:
            raise ValidationError(
                f"Manifest profile '{profile}' uses the retired "
                "'spatial.manifest@MAJOR.MINOR' form; 1.7 requires "
                "'spatial.manifest/1.<minor>'"
            )
        match = re.match(cls.MANIFEST_PROFILE_PATTERN, profile)
        if not match:
            raise ValidationError(
                f"Invalid manifest profile '{profile}' "
                "(expected 'spatial.manifest/1.<minor>')"
            )
        minor = int(match.group(1))
        if minor < cls.MANIFEST_MIN_MINOR:
            raise ValidationError(
                f"Manifest profile '{profile}' predates 1.7; minor must be "
                f">= {cls.MANIFEST_MIN_MINOR}"
            )

    @classmethod
    def validate_service_summary(cls, summary: Dict[str, Any]) -> None:
        """
        Validate disco::ServiceSummary — the compact row 1.7 returns from
        CoverageResponse in place of a full Announce.

        Full capabilities, topics and transforms are no longer inlined;
        consumers resolve ``manifest_uri`` or read the retained Announce.
        """
        if not isinstance(summary, dict):
            raise ValidationError("ServiceSummary must be an object")
        if not summary.get("service_id"):
            raise ValidationError("ServiceSummary.service_id is required")
        kind = summary.get("kind")
        if kind not in cls.VALID_SERVICE_KINDS:
            raise ValidationError(
                f"Invalid ServiceSummary.kind '{kind}' "
                f"(expected one of {sorted(cls.VALID_SERVICE_KINDS)})"
            )
        if not summary.get("manifest_uri"):
            raise ValidationError("ServiceSummary.manifest_uri is required")
        cls.validate_spatial_uri(summary["manifest_uri"])
        for absent in ("caps", "topics", "transforms"):
            if absent in summary:
                raise ValidationError(
                    f"ServiceSummary must not carry '{absent}'; resolve "
                    "manifest_uri or read the retained Announce instead"
                )
        coverage_frame_ref = summary.get("coverage_frame_ref")
        if coverage_frame_ref is not None:
            cls.validate_frame_ref(coverage_frame_ref)
        coverage = summary.get("coverage")
        if coverage is not None:
            cls.validate_coverage(coverage, coverage_frame_ref)
        if "stamp" in summary:
            cls.validate_time(summary["stamp"])

    @classmethod
    def validate_coverage(
        cls,
        coverage: List[Dict[str, Any]],
        coverage_frame_ref: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Validate list of CoverageElements"""
        if not isinstance(coverage, list):
            raise ValidationError("coverage must be an array of CoverageElement")
        if not coverage:
            raise ValidationError("coverage must contain at least one element")
        for idx, elem in enumerate(coverage):
            try:
                cls.validate_coverage_element(elem, coverage_frame_ref)
            except ValidationError as exc:
                raise ValidationError(f"Coverage element {idx} invalid: {exc}")

    @classmethod
    def check_coverage_intersection(
        cls,
        coverage_a: List[Dict[str, Any]],
        coverage_b: List[Dict[str, Any]],
        frame_ref_a: Optional[Dict[str, Any]] = None,
        frame_ref_b: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        The §3.3.4 intersects predicate: bbox, aabb and circle, per frame.

        The implementation lives in :mod:`spatialdds_demo.discovery_http`, the
        one module that owns discovery-binding semantics; this stays as the
        entry point the on-bus `CoverageQuery` responder and the catalogue
        server already call, so bus matching and HTTP matching cannot disagree.
        It used to have its own bbox-only copy, which meant a service
        announcing an aabb or a circle — every service in the multi-operator
        fusion demo — matched no query anywhere.

        Imported here rather than at module scope because discovery_http
        imports this class.
        """
        from spatialdds_demo.discovery_http import coverage_intersects

        return coverage_intersects(
            list(coverage_a or []), list(coverage_b or []),
            query_frame_ref=frame_ref_a, record_frame_ref=frame_ref_b,
        )


def complete_coverage_element(**fields: Any) -> Dict[str, Any]:
    """
    A fully-populated `CoverageElement`.

    The spec models optionality with an explicit `has_x` flag beside a value
    rather than a nullable field, so every member carries a value whatever the
    flag says. Emitting only the fields in use produced dicts that could not be
    built into the real struct once the wire went typed, so the builders fill
    the rest in.
    """
    element: Dict[str, Any] = {
        "has_crs": False,
        "crs": "",
        "has_bbox": False,
        "bbox": [0.0, 0.0, 0.0, 0.0],
        "has_aabb": False,
        "aabb": {"min_xyz": [0.0, 0.0, 0.0], "max_xyz": [0.0, 0.0, 0.0]},
        "global": False,
        "has_frame_ref": False,
        "frame_ref": SpatialDDSValidator.create_frame_ref("earth-fixed"),
        "has_coverage_window": False,
        "coverage_window_start": {"sec": 0, "nanosec": 0},
        "coverage_window_end": {"sec": 0, "nanosec": 0},
        # Added in 1.7's findings-batch-2 revision: a circular footprint is
        # a circle now, rather than its bounding aabb reconstructed by every
        # consumer as centre + half-width.
        "has_circle": False,
        "circle_center": [0.0, 0.0, 0.0],
        "circle_radius_m": 0.0,
    }
    element.update(fields)
    return element


def create_coverage_bbox_earth_fixed(
    west: float,
    south: float,
    east: float,
    north: float,
    frame_ref: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Create a coverage_frame_ref + CoverageElement tuple for an earth-fixed bbox.
    Returns (coverage_frame_ref, coverage_element).
    """
    frame_ref = frame_ref or SpatialDDSValidator.create_frame_ref("earth-fixed")
    element = complete_coverage_element(
        has_crs=True, crs="EPSG:4979",
        has_bbox=True, bbox=[west, south, east, north],
    )
    SpatialDDSValidator.validate_frame_ref(frame_ref)
    SpatialDDSValidator.validate_coverage_element(element, frame_ref)
    return frame_ref, element


def demo_geo_pose(lat: float, lon: float, alt: float) -> Dict[str, Any]:
    """
    Create a simple GeoPose with a unit quaternion.

    1.7 removed ``frame_kind`` and ``frame_ref`` from ``core::GeoPose``:
    the orientation is *defined* to be in the local ENU tangent frame at
    the encoded position (OGC GeoPose), so there is nothing left to
    declare. The demo only ever used ENU, so this is a pure deletion.
    """
    q = [0.0, 0.0, 0.0, 1.0]
    SpatialDDSValidator.validate_quaternion_xyzw(q)
    return {
        "lat_deg": lat,
        "lon_deg": lon,
        "alt_m": alt,
        "q": q,
        "stamp": SpatialDDSValidator.now_time(),
        "cov": "COV_NONE",
    }


if __name__ == "__main__":
    print("Testing SpatialDDS v1.7 Validation...")

    # FrameRef + Time
    fr = SpatialDDSValidator.create_frame_ref("earth-fixed")
    SpatialDDSValidator.validate_frame_ref(fr)
    now = SpatialDDSValidator.now_time()
    SpatialDDSValidator.validate_time(now)
    print(f"✓ FrameRef valid: {fr}")
    print(f"✓ Time valid: {now}")

    # Quaternion
    q = [0.0, 0.0, 0.0, 1.0]
    SpatialDDSValidator.validate_quaternion_xyzw(q)
    print(f"✓ Quaternion valid: {q}")

    # Coverage
    frame_ref, elem = create_coverage_bbox_earth_fixed(-122.52, 37.70, -122.35, 37.85)
    SpatialDDSValidator.validate_coverage([elem], frame_ref)
    print(f"✓ Coverage element valid: {elem}")

    # Intersection
    _, elem2 = create_coverage_bbox_earth_fixed(-122.50, 37.72, -122.30, 37.90)
    intersects = SpatialDDSValidator.check_coverage_intersection([elem], [elem2])
    print(f"✓ Bbox intersection: {intersects}")

    # GeoPose helper (1.7: no frame_kind / frame_ref)
    pose = demo_geo_pose(37.7749, -122.4194, 15.0)
    SpatialDDSValidator.validate_geo_pose(pose)
    print(f"✓ GeoPose sample: {pose}")

    # Version strings — 1.7 only, slash form only
    SpatialDDSValidator.validate_module_version("spatial.core/1.7")
    SpatialDDSValidator.validate_manifest_profile("spatial.manifest/1.7")
    for rejected in ("spatial.core/1.6", "core@1.6"):
        try:
            SpatialDDSValidator.validate_module_version(rejected)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"{rejected} should not validate under 1.7")
    print("✓ Version strings: spatial.<profile>/1.7 only")

    # ServiceSummary — the 1.7 CoverageResponse row
    summary = {
        "service_id": "svc:vps:demo/sf-downtown",
        "kind": "VPS",
        "name": "MockVPS-v1.7",
        "manifest_uri": "spatialdds://vps.example.com/zone:sf-downtown/manifest:vps",
        "coverage": [elem],
        "coverage_frame_ref": frame_ref,
        "stamp": SpatialDDSValidator.now_time(),
        "ttl_sec": 300,
    }
    SpatialDDSValidator.validate_service_summary(summary)
    print(f"✓ ServiceSummary valid: {summary['service_id']}")

    print("\nAll validation checks completed.")
