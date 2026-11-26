# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""
Compute map coverage and write ``coverage.json`` based on the extent
of the map in its own coordinate frame (always) and its geo-alignment (if available).

Metric ``volumes[]`` and geodetic ``geo_footprint`` use **filtered COLMAP points3D**
(track support, reprojection error, horizontal distance-to-trajectory), then
convex hull in the horizontal plane (see ``colmap_model_coverage_points``).

Edge cases: omit ``geodetic_coverage`` when anchor missing, |phi_ref| > 85°,
lon span > 180°, or hull |lat| > 85° (deferred ``geo_query`` strategies).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pycolmap import Reconstruction

from colmap_model_coverage_points import (
    CoverageFilterParams,
    convex_hull_lon_lat,
    coverage_method_metadata,
    filter_points_from_reconstruction,
)
from geopose_utils import enu_to_geodetic
from map_model_gate import localization_model_signature_from_config_path

COVERAGE_SCHEMA_VERSION = 1
MAX_ABS_LAT_SUPPORTED = 85.0
WGS84_ENU_FRAME_REF = {"uuid": "OSCP:WGS84-ENU", "fqn": "OSCP:WGS84-ENU"}

GRAPHICS_TO_ROBOTICS = np.array(
    [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
    dtype=np.float64,
)


def _geodetic_ref_from_transform(data: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    lat, lon, h = data.get("latitude"), data.get("longitude"), data.get("height")
    if lat is None and lon is None and h is None:
        return None
    if lat is None or lon is None or h is None:
        raise ValueError("transform.json: set all of latitude, longitude, height or omit all")
    return float(lat), float(lon), float(h)


def _map_to_enu_matrix(data: Dict[str, Any]) -> np.ndarray:
    T = np.asarray(data["matrix"], dtype=np.float64)
    return GRAPHICS_TO_ROBOTICS @ T


def _aabb_from_points(pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    return np.min(pts, axis=0), np.max(pts, axis=0)


def _model_signature(
    colmap_model_dir: Path,
    transform_path: Path,
    n_images: int,
    n_points_kept: int,
    filter_params: CoverageFilterParams,
) -> str:
    h = hashlib.sha256()
    if transform_path.is_file():
        h.update(transform_path.read_bytes())
    if colmap_model_dir.is_dir():
        for p in sorted(colmap_model_dir.glob("*")):
            if p.is_file():
                h.update(p.name.encode())
                h.update(str(p.stat().st_mtime_ns).encode())
    h.update(str(n_images).encode())
    h.update(str(n_points_kept).encode())
    h.update(
        json.dumps(
            {
                "min_track_len": filter_params.min_track_len,
                "max_reproj_error_px": filter_params.max_reproj_error_px,
                "max_horiz_radius_m": filter_params.max_horiz_radius_m,
                "horiz_percentile": filter_params.horiz_percentile,
                "preset": filter_params.preset,
                "method": "filtered_points_convex_hull_v1",
            },
            sort_keys=True,
        ).encode()
    )
    return h.hexdigest()[:32]


def _points_to_geodetic(
    kept_xyz: np.ndarray,
    T: np.ndarray,
    lat_ref: float,
    lon_ref: float,
    h_ref: float,
) -> Tuple[List[float], List[float], List[float]]:
    lats: List[float] = []
    lons: List[float] = []
    alts: List[float] = []
    for p in kept_xyz:
        ph = np.concatenate([p, [1.0]])
        enu = (T @ ph)[:3]
        lat, lon, alt = enu_to_geodetic(
            float(enu[0]), float(enu[1]), float(enu[2]), lat_ref, lon_ref, h_ref
        )
        lats.append(lat)
        lons.append(lon)
        alts.append(alt)
    return lats, lons, alts


def compute_coverage(
    colmap_model_dir: Path,
    transform_path: Path,
    map_id: str,
    filter_params: Optional[CoverageFilterParams] = None,
) -> Dict[str, Any]:
    if not colmap_model_dir.is_dir():
        raise FileNotFoundError(f"missing COLMAP model: {colmap_model_dir}")

    params = filter_params or CoverageFilterParams.from_preset("outdoor")
    reconstruction = Reconstruction(str(colmap_model_dir))
    kept_xyz, _centers, stats = filter_points_from_reconstruction(reconstruction, params)

    mn, mx = _aabb_from_points(kept_xyz)
    frame_ref = {"uuid": map_id, "fqn": f"openvps/hloc/{map_id}/colmap_world"}
    volumes = [
        {
            "frame_ref": frame_ref,
            "aabb": {"min_xyz": mn.tolist(), "max_xyz": mx.tolist()},
            "source": "colmap_points_filtered" if not stats.used_camera_fallback else "colmap_cameras",
        }
    ]

    geodetic_block: Optional[Dict[str, Any]] = None
    transform_data: Dict[str, Any] = {"matrix": np.eye(4).tolist()}
    if transform_path.is_file():
        with open(transform_path, "r", encoding="utf-8") as f:
            transform_data = json.load(f)

    ref = _geodetic_ref_from_transform(transform_data)
    if ref is not None:
        lat_ref, lon_ref, h_ref = ref
        if abs(lat_ref) > MAX_ABS_LAT_SUPPORTED:
            print(
                f"warning: |phi_ref|={abs(lat_ref):.2f}° > {MAX_ABS_LAT_SUPPORTED}°; omitting geodetic_coverage",
                file=sys.stderr,
            )
        else:
            T = _map_to_enu_matrix(transform_data)
            lats, lons, alts = _points_to_geodetic(kept_xyz, T, lat_ref, lon_ref, h_ref)
            lon_span = max(lons) - min(lons)
            if lon_span > 180.0:
                print("warning: hull lon span > 180°; omitting geodetic_coverage (antimeridian)", file=sys.stderr)
            elif max(abs(min(lats)), abs(max(lats))) > MAX_ABS_LAT_SUPPORTED:
                print("warning: coverage |lat| > 85°; omitting geodetic_coverage", file=sys.stderr)
            else:
                ring = convex_hull_lon_lat(list(zip(lons, lats)))
                geo_aabb = {
                    "lon_min": min(lons),
                    "lat_min": min(lats),
                    "alt_min": min(alts),
                    "lon_max": max(lons),
                    "lat_max": max(lats),
                    "alt_max": max(alts),
                }
                geodetic_block = {
                    "frame_ref": WGS84_ENU_FRAME_REF,
                    "geo_aabb": geo_aabb,
                    "geo_query": {"schema": 1, "strategy": "standard"},
                }
                if ring:
                    geodetic_block["geo_footprint"] = {"type": "Polygon", "coordinates": [ring]}

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out: Dict[str, Any] = {
        "coverage_schema_version": COVERAGE_SCHEMA_VERSION,
        "map_id": map_id,
        "model_signature": _model_signature(
            colmap_model_dir,
            transform_path,
            len(reconstruction.images),
            stats.points_kept,
            params,
        ),
        "computed_at": now,
        "volumes": volumes,
        "coverage_method": coverage_method_metadata(params, stats),
    }
    if geodetic_block is not None:
        out["geodetic_coverage"] = geodetic_block

    config_path = transform_path.parent / "config.yaml"
    loc_sig, _, loc_desc = localization_model_signature_from_config_path(config_path)
    if loc_sig is not None:
        out["localization_model_signature"] = loc_sig
    if loc_desc is not None:
        out["localization_model"] = loc_desc
    return out


def _build_filter_params(args: argparse.Namespace) -> CoverageFilterParams:
    overrides: Dict[str, Any] = {}
    if args.min_track_len is not None:
        overrides["min_track_len"] = args.min_track_len
    if args.max_reproj_error_px is not None:
        overrides["max_reproj_error_px"] = args.max_reproj_error_px
    if args.max_horiz_radius_m is not None:
        overrides["max_horiz_radius_m"] = args.max_horiz_radius_m
    if args.horiz_percentile is not None:
        overrides["horiz_percentile"] = args.horiz_percentile
    if args.preset:
        return CoverageFilterParams.from_preset(args.preset, **overrides)
    if overrides:
        return CoverageFilterParams(
            min_track_len=int(overrides.get("min_track_len", 3)),
            max_reproj_error_px=float(overrides.get("max_reproj_error_px", 4.0)),
            max_horiz_radius_m=float(overrides.get("max_horiz_radius_m", 50.0)),
            horiz_percentile=float(overrides.get("horiz_percentile", 90.0)),
            preset=None,
        )
    return CoverageFilterParams.from_preset("outdoor")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write OpenVPS coverage.json (v1)")
    parser.add_argument("--map_id", type=str, required=True, help="Global map UUID (coverage artifact + frame_ref)")
    parser.add_argument(
        "--colmap_model_dir",
        type=str,
        required=True,
        help="COLMAP reconstruction directory",
    )
    parser.add_argument(
        "--transform_path",
        type=str,
        required=True,
        help="Map alignment transform JSON (geo anchor + map-to-ENU matrix)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to write coverage.json",
    )
    parser.add_argument(
        "--preset",
        type=str,
        choices=["indoor", "outdoor"],
        default="outdoor",
        help="Horizontal radius cap preset (outdoor 50m, indoor 15m)",
    )
    parser.add_argument("--min_track_len", type=int, default=None, help="Minimum point track length (default 3)")
    parser.add_argument(
        "--max_reproj_error_px",
        type=float,
        default=None,
        help="Max COLMAP point reprojection error in px (default 4)",
    )
    parser.add_argument(
        "--max_horiz_radius_m",
        type=float,
        default=None,
        help="Cap horizontal distance-to-camera threshold (m)",
    )
    parser.add_argument(
        "--horiz_percentile",
        type=float,
        default=None,
        help="Percentile of horizontal camera distances for threshold (default 90)",
    )
    args = parser.parse_args()
    colmap_model_dir = Path(args.colmap_model_dir)
    transform_path = Path(args.transform_path)
    out_path = Path(args.output)
    filter_params = _build_filter_params(args)
    try:
        payload = compute_coverage(colmap_model_dir, transform_path, str(args.map_id), filter_params)
    except Exception as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(out_path)
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
