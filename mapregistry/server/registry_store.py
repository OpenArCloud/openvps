# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

from __future__ import annotations

import json
from pathlib import Path

from coverage_schema import MapCoverageRecord, RegistryIndex, SCHEMA_VERSION


def load_index(path: Path) -> RegistryIndex:
    if not path.exists():
        return RegistryIndex()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    maps_raw = raw.get("maps") or {}
    maps = {}
    for k, v in maps_raw.items():
        maps[k] = MapCoverageRecord.model_validate(v)
    return RegistryIndex(schema_version=raw.get("schema_version", SCHEMA_VERSION), maps=maps)


def save_index(path: Path, index: RegistryIndex) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index.to_json_dict(), f, indent=2)
    tmp.replace(path)


def upsert_record(path: Path, record: MapCoverageRecord) -> RegistryIndex:
    idx = load_index(path)
    idx.maps[record.map_id] = record
    save_index(path, idx)
    return idx
