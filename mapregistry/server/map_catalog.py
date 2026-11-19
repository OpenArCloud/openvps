# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

"""Enumerate HLOC map folders under the uploads volume (local map catalog)."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple


class MapRef(NamedTuple):
    """Stable reference to a map's on-disk (or future remote) root."""

    map_id: str
    dataset_id: str
    path: Path

    @property
    def root_uri(self) -> str:
        return self.path.as_uri()


def enumerate_hloc_maps(
    uploads_root: Path,
    *,
    on_duplicate: str = "last_wins",
) -> Dict[str, MapRef]:
    """map_id -> MapRef (dataset_id + absolute path to map folder).

    The **canonical API and index key is global ``map_id``** (MapBuilder UUID =
    ``hlocMaps/{mapId}/`` folder name). ``dataset_id`` is uploads-layout metadata
    (MapBuilder upload folder name) only.

    Same discovery layout as maplocalizer ``HlocLocalizer.get_all_map_ids_and_paths``.

    If the same ``map_id`` appears under two datasets: ``on_duplicate`` is
    ``last_wins`` (default, lexicographic dataset dir order) or ``error``.
    """
    out: Dict[str, MapRef] = {}
    if not uploads_root.is_dir():
        return out
    for ds_dir in sorted(uploads_root.iterdir(), key=lambda p: p.name):
        if not ds_dir.is_dir():
            continue
        status = ds_dir / "status.json"
        if not status.is_file():
            continue
        hloc_maps = ds_dir / "hlocMaps"
        if not hloc_maps.is_dir():
            continue
        dataset_id = ds_dir.name
        for map_dir in hloc_maps.iterdir():
            if not map_dir.is_dir():
                continue
            mid = map_dir.name
            ref = MapRef(map_id=mid, dataset_id=dataset_id, path=map_dir.resolve())
            if mid in out:
                prev = out[mid]
                msg = (
                    f"duplicate map_id {mid!r}: dataset {prev.dataset_id!r} ({prev.path}) "
                    f"and {dataset_id!r} ({ref.path})"
                )
                if on_duplicate == "error":
                    raise ValueError(msg)
                warnings.warn(msg, stacklevel=2)
            out[mid] = ref
    return out


def list_hloc_map_refs_raw(uploads_root: Path) -> List[MapRef]:
    """All map refs without de-duplicating by map_id (diagnostics)."""
    refs: List[MapRef] = []
    if not uploads_root.is_dir():
        return refs
    for ds_dir in uploads_root.iterdir():
        if not ds_dir.is_dir():
            continue
        if not (ds_dir / "status.json").is_file():
            continue
        hloc_maps = ds_dir / "hlocMaps"
        if not hloc_maps.is_dir():
            continue
        dataset_id = ds_dir.name
        for map_dir in hloc_maps.iterdir():
            if map_dir.is_dir():
                refs.append(
                    MapRef(map_id=map_dir.name, dataset_id=dataset_id, path=map_dir.resolve())
                )
    return refs


def find_duplicate_map_ids(uploads_root: Path) -> List[Tuple[str, List[MapRef]]]:
    """map_ids that appear under more than one dataset (startup / operator diagnostics)."""
    by_id: Dict[str, List[MapRef]] = {}
    for ref in list_hloc_map_refs_raw(uploads_root):
        by_id.setdefault(ref.map_id, []).append(ref)
    return [(mid, refs) for mid, refs in sorted(by_id.items()) if len(refs) > 1]


def list_hloc_map_refs(uploads_root: Path) -> List[MapRef]:
    return list(enumerate_hloc_maps(uploads_root).values())
