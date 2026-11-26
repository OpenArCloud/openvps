#!/usr/bin/env python3
"""
One-off: build global_features.h5 for legacy OpenVPS maps (not part of the repo pipeline).

Run inside the MapBuilder backend container (GPU + HLOC; script is baked in at /app/scripts):

  docker compose exec backend python3 /app/scripts/hloc_backfill_global_features.py \\
    --uploads-dir /uploads --map-id <uuid>

Optional path rewrite if config.yaml still has host paths:
  --rewrite-from /path/on/host --rewrite-to /uploads
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pycolmap
import yaml
from hloc import extract_features


def rewrite_hloc_cfg_paths(
    cfg: Dict[str, Any],
    rewrite_from: Optional[str],
    rewrite_to: Optional[str],
) -> Dict[str, Any]:
    if not rewrite_from or not rewrite_to:
        return cfg
    out = dict(cfg)
    for key, val in out.items():
        if isinstance(val, str) and rewrite_from in val:
            out[key] = val.replace(rewrite_from, rewrite_to)
    return out


def image_names_for_extract(cfg: Dict[str, Any]) -> List[str]:
    images_path = Path(cfg["image_path"])
    recon_path = Path(cfg["reconstruction_path"])
    if recon_path.is_dir():
        try:
            reconstruction = pycolmap.Reconstruction()
            reconstruction.read(str(recon_path))
            names = [img.name for img in reconstruction.images.values()]
            if names:
                return names
        except Exception as exc:
            print(f"WARNING: COLMAP read {recon_path}: {exc}", flush=True)
    if not images_path.is_dir():
        return []
    return [
        str(p.relative_to(images_path))
        for p in images_path.iterdir()
        if p.is_file()
    ]


def extract_globals(cfg: Dict[str, Any], *, force: bool = False) -> tuple[bool, str]:
    retrieval_name = cfg.get("retrieval_conf")
    if not retrieval_name:
        return False, "no retrieval_conf"

    recon_path = Path(cfg["reconstruction_path"])
    global_path = recon_path / "global_features.h5"
    if global_path.is_file() and not force:
        return True, "skip (exists)"

    images_path = Path(cfg["image_path"])
    if not images_path.is_dir():
        return False, f"bad image_path: {images_path}"
    if not recon_path.is_dir():
        return False, f"bad reconstruction_path: {recon_path}"
    if not (recon_path / "features.h5").is_file():
        return False, "missing features.h5"

    image_names = image_names_for_extract(cfg)
    if not image_names:
        return False, "no images"

    try:
        retrieval_conf = extract_features.confs[retrieval_name]
    except KeyError:
        return False, f"unknown retrieval_conf {retrieval_name!r}"

    print(
        f"Extracting {len(image_names)} images → {global_path} ({retrieval_name})",
        flush=True,
    )
    extract_features.main(
        retrieval_conf,
        images_path,
        image_list=image_names,
        feature_path=global_path,
    )
    if not global_path.is_file():
        return False, "extract did not create file"
    return True, f"wrote {global_path}"


@dataclass
class MapJob:
    map_id: str
    dataset_id: str
    config_path: Path


def discover_maps(uploads_root: Path) -> List[MapJob]:
    jobs: List[MapJob] = []
    if not uploads_root.is_dir():
        return jobs
    for ds_dir in sorted(uploads_root.iterdir(), key=lambda p: p.name):
        if not ds_dir.is_dir() or not (ds_dir / "status.json").is_file():
            continue
        hloc_maps = ds_dir / "hlocMaps"
        if not hloc_maps.is_dir():
            continue
        for map_dir in sorted(hloc_maps.iterdir(), key=lambda p: p.name):
            cfg = map_dir / "config.yaml"
            if map_dir.is_dir() and cfg.is_file():
                jobs.append(MapJob(map_dir.name, ds_dir.name, cfg))
    return jobs


def load_hloc_cfg(
    config_path: Path,
    rewrite_from: Optional[str],
    rewrite_to: Optional[str],
) -> Optional[Dict[str, Any]]:
    try:
        with open(config_path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        print(f"ERROR {config_path}: {exc}", flush=True)
        return None
    hr = doc.get("hloc_reconstruction") if isinstance(doc, dict) else None
    if not isinstance(hr, dict):
        print(f"ERROR missing hloc_reconstruction in {config_path}", flush=True)
        return None
    return rewrite_hloc_cfg_paths(hr, rewrite_from, rewrite_to)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="One-off global_features.h5 backfill")
    p.add_argument("--uploads-dir", default=os.environ.get("UPLOADS_DIR", "/uploads"))
    p.add_argument("--map-id", action="append", default=[], dest="map_ids")
    p.add_argument("--rewrite-from", default=None)
    p.add_argument("--rewrite-to", default="/uploads")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    uploads_root = Path(args.uploads_dir)
    filter_ids: Set[str] = set(args.map_ids)
    jobs = discover_maps(uploads_root)
    if filter_ids:
        jobs = [j for j in jobs if j.map_id in filter_ids]
    if not jobs:
        print(f"No maps under {uploads_root}")
        return 0

    failures = 0
    for job in jobs:
        label = f"{job.dataset_id}/{job.map_id}"
        cfg = load_hloc_cfg(job.config_path, args.rewrite_from, args.rewrite_to)
        if cfg is None:
            failures += 1
            continue

        global_path = Path(cfg["reconstruction_path"]) / "global_features.h5"
        if not cfg.get("retrieval_conf"):
            print(f"{label}: skip (no retrieval_conf)")
            continue
        if global_path.is_file() and not args.force:
            print(f"{label}: skip (exists)")
            continue

        print(f"\n=== {label} ===", flush=True)
        if args.dry_run:
            print(f"dry-run: would write {global_path}")
            continue

        t0 = time.perf_counter()
        try:
            ok, msg = extract_globals(cfg, force=args.force)
        except Exception:
            traceback.print_exc()
            ok, msg = False, "exception"
        print(f"{label}: {msg} ({time.perf_counter() - t0:.1f}s)", flush=True)
        if not ok:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())