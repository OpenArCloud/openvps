# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)
#
# Align HLOC COLMAP reconstruction to StrayScanner prior (metric) via Sim(3), then either
# rescale the sparse model in place or record meters-per-map-unit in transform.json.

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pycolmap


def _qvec_to_rotmat(qvec) -> np.ndarray:
    """COLMAP world-to-camera rotation from unit quaternion (w, x, y, z)."""
    qw, qx, qy, qz = [float(x) for x in qvec]
    return np.array(
        [
            [
                1.0 - 2.0 * qy * qy - 2.0 * qz * qz,
                2.0 * qx * qy - 2.0 * qz * qw,
                2.0 * qx * qz + 2.0 * qy * qw,
            ],
            [
                2.0 * qx * qy + 2.0 * qz * qw,
                1.0 - 2.0 * qx * qx - 2.0 * qz * qz,
                2.0 * qy * qz - 2.0 * qx * qw,
            ],
            [
                2.0 * qx * qz - 2.0 * qy * qw,
                2.0 * qy * qz + 2.0 * qx * qw,
                1.0 - 2.0 * qx * qx - 2.0 * qy * qy,
            ],
        ],
        dtype=np.float64,
    )


def _image_world_center(image: pycolmap.Image) -> np.ndarray:
    """Camera projection center in world coordinates (3,)."""
    try:
        return np.asarray(image.projection_center(), dtype=np.float64).reshape(3)
    except Exception:
        pass
    pose = getattr(image, "cam_from_world", None)
    if pose is not None:
        if callable(pose):
            pose = pose()
        try:
            R = np.asarray(pose.rotation.matrix(), dtype=np.float64).reshape(3, 3)
            t = np.asarray(pose.translation, dtype=np.float64).reshape(3)
            return -(R.T @ t)
        except Exception:
            pass
    if hasattr(image, "qvec") and hasattr(image, "tvec"):
        R = _qvec_to_rotmat(image.qvec)
        t = np.asarray(image.tvec, dtype=np.float64).reshape(3)
        return -(R.T @ t)
    raise RuntimeError("Could not compute camera center for image")


def _gather_centers_by_name(rec: pycolmap.Reconstruction) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    for _id, im in rec.images.items():
        name = im.name
        if not name:
            continue
        out[name] = _image_world_center(im)
    return out


def _has_spread(prior_centers: List[np.ndarray], min_pair_m: float) -> bool:
    if len(prior_centers) < 2:
        return False
    arr = np.stack(prior_centers, axis=0)
    # O(n^2) is fine for filtered Stray models (hundreds of images at most).
    for i in range(arr.shape[0]):
        d = np.linalg.norm(arr[i] - arr[i + 1 :], axis=1)
        if np.any(d >= min_pair_m):
            return True
    return False


def _estimate_sim3_numpy(src: np.ndarray, tgt: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """Least-squares similarity tgt ~ s * R @ src + t with src,tgt as Nx3 row vectors.

    Returns R (3x3), t (3,), s such that each row tgt[i] ~ s * (R @ src[i]) + t
    with src[i] as column in the product: actually tgt_i^T = s * R @ src_i^T + t
    => tgt_i = s * src_i @ R.T + t_row.
    """
    if src.shape != tgt.shape or src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("src and tgt must be Nx3 with identical shapes")
    n = src.shape[0]
    if n < 3:
        raise ValueError("Need at least 3 point correspondences for Sim(3)")
    X = src.T  # 3 x N columns
    Y = tgt.T
    mx = X.mean(axis=1, keepdims=True)
    my = Y.mean(axis=1, keepdims=True)
    Xc = X - mx
    Yc = Y - my
    K = Yc @ Xc.T / float(n)
    U, D, Vt = np.linalg.svd(K)
    Z = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        Z[2, 2] = -1.0
    R = U @ Z @ Vt
    var_x = float((Xc**2).sum() / n)
    if var_x < 1e-20:
        raise ValueError("Degenerate spread in HLOC camera centers (var_x too small)")
    s = float(np.trace(np.diag(D) @ Z) / var_x)
    if not np.isfinite(s) or s <= 0:
        raise ValueError(f"Invalid similarity scale from Umeyama: {s}")
    t_col = my - s * (R @ mx)
    t = t_col.reshape(3)
    return R, t, s


def _sim3d_from_numpy(R: np.ndarray, t: np.ndarray, s: float) -> pycolmap.Sim3d:
    """Build pycolmap.Sim3d for new_from_old_world: x_new = s * R @ x_old + t (column)."""
    A = (s * R).astype(np.float64)
    mat = np.hstack([A, t.reshape(3, 1).astype(np.float64)])
    try:
        return pycolmap.Sim3d(mat)
    except Exception:
        pass
    try:
        rot = pycolmap.Rotation3d(R)
        return pycolmap.Sim3d(float(s), rot, t.astype(np.float64))
    except Exception as ex:
        raise RuntimeError(f"Could not construct pycolmap.Sim3d: {ex}") from ex


def _estimate_sim3_pycolmap_or_numpy(
    src: np.ndarray, tgt: np.ndarray
) -> Tuple[pycolmap.Sim3d, np.ndarray, np.ndarray, float]:
    """Return (Sim3d, R, t, s) with tgt ~ s * src @ R.T + t for rows."""
    est = getattr(pycolmap, "estimate_sim3d", None)
    if est is not None:
        sim = est(src.astype(np.float64), tgt.astype(np.float64))
        if sim is not None:
            M = np.asarray(sim.matrix(), dtype=np.float64)
            A = M[:, :3]
            t = M[:, 3].reshape(3)
            col_norms = np.linalg.norm(A, axis=0)
            s = float(np.mean(col_norms)) if col_norms.size == 3 else 1.0
            R = A / s if s > 1e-12 else A
            return sim, R, t, s
    R, t, s = _estimate_sim3_numpy(src, tgt)
    sim = _sim3d_from_numpy(R, t, s)
    return sim, R, t, s


def _uniform_scale_from_sim3(sim: pycolmap.Sim3d) -> float:
    sc = getattr(sim, "scale", None)
    if sc is not None and np.isfinite(float(sc)) and float(sc) > 0:
        return float(sc)
    M = np.asarray(sim.matrix(), dtype=np.float64)
    A = M[:, :3]
    col_norms = np.linalg.norm(A, axis=0)
    if col_norms.size != 3 or not np.all(np.isfinite(col_norms)):
        return 1.0
    return float(np.mean(col_norms))


def _rms_with_sim3(src: np.ndarray, tgt: np.ndarray, sim: pycolmap.Sim3d) -> float:
    M = np.asarray(sim.matrix(), dtype=np.float64)
    A, t = M[:, :3], M[:, 3]
    pred = (src @ A.T) + t.reshape(1, 3)
    err = np.linalg.norm(pred - tgt, axis=1)
    return float(np.sqrt(np.mean(err**2)))


def run_metric_alignment(
    prior_model_path: Path,
    reconstruction_path: Path,
    transform_json_path: Path,
    mode: str,
    min_shared_images: int,
    min_pair_distance_m: float,
) -> Dict[str, Any]:
    mode = str(mode).strip().lower()
    if mode not in ("rescale_model", "coord_scale_only"):
        raise ValueError("mode must be rescale_model or coord_scale_only")

    prior = pycolmap.Reconstruction()
    prior.read(str(prior_model_path))
    hloc = pycolmap.Reconstruction()
    hloc.read(str(reconstruction_path))

    prior_c = _gather_centers_by_name(prior)
    hloc_c = _gather_centers_by_name(hloc)
    names = sorted(set(prior_c.keys()) & set(hloc_c.keys()))
    if len(names) < min_shared_images:
        raise RuntimeError(
            f"metric alignment: only {len(names)} shared images (need >= {min_shared_images})"
        )

    prior_centers_list = [prior_c[n] for n in names]
    if not _has_spread(prior_centers_list, min_pair_distance_m):
        raise RuntimeError(
            f"metric alignment: no camera pair in prior with separation >= {min_pair_distance_m} m"
        )

    src = np.stack([hloc_c[n] for n in names], axis=0)
    tgt = np.stack([prior_c[n] for n in names], axis=0)

    sim, _, _, _ = _estimate_sim3_pycolmap_or_numpy(src, tgt)
    rms = _rms_with_sim3(src, tgt, sim)
    s_uniform = _uniform_scale_from_sim3(sim)

    diag: Dict[str, Any] = {
        "mode": mode,
        "num_shared_images": len(names),
        "rms_prior_vs_sim3_m": rms,
        "similarity_scale": s_uniform,
    }

    if mode == "rescale_model":
        hloc.transform(sim)
        hloc.write(str(reconstruction_path))
        scale_factor = 1.0
    else:
        scale_factor = s_uniform

    payload: Dict[str, Any] = {
        "latitude": None,
        "longitude": None,
        "height": None,
        "matrix": [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ],
        "coord_scale": {"target_unit": "SI_METER", "scale_factor": scale_factor},
        "metric_alignment": diag,
    }

    transform_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transform_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return diag


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Metric alignment of HLOC reconstruction to Stray prior")
        parser.add_argument("--prior_model_path", type=str, required=True)
        parser.add_argument("--reconstruction_path", type=str, required=True)
        parser.add_argument("--transform_json_path", type=str, required=True)
        parser.add_argument(
            "--mode",
            type=str,
            required=True,
            choices=("rescale_model", "coord_scale_only"),
        )
        parser.add_argument("--min_shared_images", type=int, default=4)
        parser.add_argument("--min_pair_distance_m", type=float, default=0.05)
        args = parser.parse_args()
        run_metric_alignment(
            Path(args.prior_model_path),
            Path(args.reconstruction_path),
            Path(args.transform_json_path),
            args.mode,
            int(args.min_shared_images),
            float(args.min_pair_distance_m),
        )
        print("Metric alignment finished; wrote", args.transform_json_path)
    except Exception as ex:
        print("Exception occurred: " + str(ex))
        print("hloc_metric_alignment failed")
        exit(-1)
