# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

"""Heuristic COLMAP points3D filtering for map coverage footprints."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from pycolmap import Reconstruction

P_PRESETS: Dict[str, Dict[str, float]] = {
    "indoor": {"max_horiz_radius_m": 15.0},
    "outdoor": {"max_horiz_radius_m": 50.0},
}

LARGE_MAP_POINT_THRESHOLD = 500_000
P90_SUBSAMPLE = 200_000


@dataclass(frozen=True)
class CoverageFilterParams:
    min_track_len: int = 3
    max_reproj_error_px: float = 4.0
    max_horiz_radius_m: float = 50.0
    horiz_percentile: float = 90.0
    preset: Optional[str] = None

    @classmethod
    def from_preset(cls, preset: str, **overrides: Any) -> "CoverageFilterParams":
        if preset not in P_PRESETS:
            raise ValueError(f"unknown preset {preset!r}; use indoor|outdoor")
        vals: Dict[str, Any] = {
            "max_horiz_radius_m": P_PRESETS[preset]["max_horiz_radius_m"],
            "preset": preset,
        }
        vals.update(overrides)
        return cls(
            min_track_len=int(vals.get("min_track_len", 3)),
            max_reproj_error_px=float(vals.get("max_reproj_error_px", 4.0)),
            max_horiz_radius_m=float(vals["max_horiz_radius_m"]),
            horiz_percentile=float(vals.get("horiz_percentile", 90.0)),
            preset=str(vals.get("preset")),
        )


@dataclass
class CoverageFilterStats:
    points_total: int
    points_kept: int
    cameras_n: int
    used_camera_fallback: bool
    horiz_threshold_m: float


def _track_length(point: Any) -> int:
    track = point.track
    if hasattr(track, "length"):
        return int(track.length())
    if hasattr(track, "num_elements"):
        return int(track.num_elements())
    elements = getattr(track, "elements", None)
    if elements is not None:
        return len(list(elements))
    return 1


def camera_centers_array(reconstruction: Reconstruction) -> np.ndarray:
    pts: List[np.ndarray] = []
    for image in reconstruction.images.values():
        c = image.projection_center()
        pts.append(np.asarray(c, dtype=np.float64).reshape(3))
    if not pts:
        raise RuntimeError("COLMAP model has no registered images")
    return np.stack(pts, axis=0)


def load_points_arrays(reconstruction: Reconstruction) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    xyz: List[np.ndarray] = []
    track_lens: List[int] = []
    errors: List[float] = []
    for point in reconstruction.points3D.values():
        xyz.append(np.asarray(point.xyz, dtype=np.float64).reshape(3))
        track_lens.append(_track_length(point))
        errors.append(float(point.error))
    if not xyz:
        empty = np.zeros((0, 3), dtype=np.float64)
        return empty, np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)
    return (
        np.stack(xyz, axis=0),
        np.asarray(track_lens, dtype=np.int64),
        np.asarray(errors, dtype=np.float64),
    )


def vertical_axis_from_cameras(centers: np.ndarray) -> int:
    mn, mx = np.min(centers, axis=0), np.max(centers, axis=0)
    extents = mx - mn
    return int(np.argmin(extents))


def _drop_axis(coords: np.ndarray, vertical_axis: int) -> np.ndarray:
    axes = [0, 1, 2]
    axes.remove(vertical_axis)
    return coords[:, axes]


def _horizontal_distances_to_cameras(
    points: np.ndarray,
    cameras: np.ndarray,
    vertical_axis: int,
) -> np.ndarray:
    from scipy.spatial import cKDTree  # type: ignore

    p2 = _drop_axis(points, vertical_axis)
    c2 = _drop_axis(cameras, vertical_axis)
    tree = cKDTree(c2)
    dists, _ = tree.query(p2, k=1)
    return np.asarray(dists, dtype=np.float64)


def _horiz_distance_threshold(
    distances: np.ndarray,
    params: CoverageFilterParams,
) -> float:
    if distances.size == 0:
        return params.max_horiz_radius_m
    if distances.size > P90_SUBSAMPLE:
        idx = np.linspace(0, distances.size - 1, P90_SUBSAMPLE, dtype=np.int64)
        sample = distances[idx]
    else:
        sample = distances
    p = float(np.percentile(sample, params.horiz_percentile))
    return float(min(p, params.max_horiz_radius_m))


def filter_coverage_points(
    points_xyz: np.ndarray,
    track_lens: np.ndarray,
    errors: np.ndarray,
    camera_centers: np.ndarray,
    params: CoverageFilterParams,
    vertical_axis: Optional[int] = None,
) -> Tuple[np.ndarray, CoverageFilterStats]:
    cameras_n = int(camera_centers.shape[0])
    points_total = int(points_xyz.shape[0])
    v_axis = vertical_axis if vertical_axis is not None else vertical_axis_from_cameras(camera_centers)

    if points_total == 0:
        print("warning: no points3D; falling back to camera centers", file=sys.stderr)
        return camera_centers.copy(), CoverageFilterStats(
            points_total=0,
            points_kept=cameras_n,
            cameras_n=cameras_n,
            used_camera_fallback=True,
            horiz_threshold_m=params.max_horiz_radius_m,
        )

    mask = track_lens >= params.min_track_len
    mask &= errors <= params.max_reproj_error_px
    distances = _horizontal_distances_to_cameras(points_xyz, camera_centers, v_axis)
    horiz_threshold = _horiz_distance_threshold(distances, params)
    mask &= distances <= horiz_threshold

    kept = points_xyz[mask]
    if kept.shape[0] < 3:
        print(
            f"warning: only {kept.shape[0]} points after filter; falling back to camera centers",
            file=sys.stderr,
        )
        return camera_centers.copy(), CoverageFilterStats(
            points_total=points_total,
            points_kept=int(kept.shape[0]),
            cameras_n=cameras_n,
            used_camera_fallback=True,
            horiz_threshold_m=horiz_threshold,
        )

    return kept, CoverageFilterStats(
        points_total=points_total,
        points_kept=int(kept.shape[0]),
        cameras_n=cameras_n,
        used_camera_fallback=False,
        horiz_threshold_m=horiz_threshold,
    )


def filter_points_from_reconstruction(
    reconstruction: Reconstruction,
    params: CoverageFilterParams,
) -> Tuple[np.ndarray, np.ndarray, CoverageFilterStats]:
    """Returns (kept_xyz map frame, camera_centers, stats)."""
    centers = camera_centers_array(reconstruction)
    points_xyz, track_lens, errors = load_points_arrays(reconstruction)
    if points_xyz.shape[0] > LARGE_MAP_POINT_THRESHOLD:
        print(
            f"warning: {points_xyz.shape[0]} points3D; distance percentile uses subsample",
            file=sys.stderr,
        )
    kept, stats = filter_coverage_points(points_xyz, track_lens, errors, centers, params)
    return kept, centers, stats


def aabb_from_points(pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    return np.min(pts, axis=0), np.max(pts, axis=0)


def convex_hull_ring_2d(xy: np.ndarray) -> Optional[List[List[float]]]:
    if xy.shape[0] < 3:
        return None
    try:
        from scipy.spatial import ConvexHull  # type: ignore
    except ImportError:
        xs, ys = xy[:, 0], xy[:, 1]
        ring = [
            [float(min(xs)), float(min(ys))],
            [float(max(xs)), float(min(ys))],
            [float(max(xs)), float(max(ys))],
            [float(min(xs)), float(max(ys))],
            [float(min(xs)), float(min(ys))],
        ]
        return ring
    try:
        hull = ConvexHull(xy)
    except Exception:
        xs, ys = xy[:, 0], xy[:, 1]
        return [
            [float(min(xs)), float(min(ys))],
            [float(max(xs)), float(min(ys))],
            [float(max(xs)), float(max(ys))],
            [float(min(xs)), float(max(ys))],
            [float(min(xs)), float(min(ys))],
        ]
    ring: List[List[float]] = []
    for idx in hull.vertices:
        ring.append([float(xy[idx, 0]), float(xy[idx, 1])])
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def convex_hull_lon_lat(points: Sequence[Tuple[float, float]]) -> Optional[List[List[float]]]:
    if len(points) < 3:
        return None
    xy = np.array([[p[0], p[1]] for p in points], dtype=np.float64)
    return convex_hull_ring_2d(xy)


def coverage_method_metadata(
    params: CoverageFilterParams,
    stats: CoverageFilterStats,
) -> Dict[str, Any]:
    return {
        "name": "filtered_points_convex_hull_v1",
        "params": {
            "min_track_len": params.min_track_len,
            "max_reproj_error_px": params.max_reproj_error_px,
            "max_horiz_radius_m": params.max_horiz_radius_m,
            "horiz_percentile": params.horiz_percentile,
            "preset": params.preset,
        },
        "stats": {
            **asdict(stats),
        },
    }
