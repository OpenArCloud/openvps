# Copyright 2026 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

"""HLOC neural model signature (keep in sync with maplocalizer/server/map_model_gate.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

_LOCALIZATION_SIG_VERSION = 1


def _norm_opt(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def localization_model_descriptor_from_config(config: Dict[str, Any]) -> Dict[str, str]:
    hr = config.get("hloc_reconstruction")
    if not isinstance(hr, dict):
        raise ValueError("config.yaml: missing hloc_reconstruction")
    return {
        "feature_conf": _norm_opt(hr.get("feature_conf")),
        "matcher_conf": _norm_opt(hr.get("matcher_conf")),
        "retrieval_conf": _norm_opt(hr.get("retrieval_conf")),
        "pairs_strategy": _norm_opt(hr.get("pairs_strategy")),
    }


def localization_model_signature_from_descriptor(descriptor: Dict[str, str]) -> str:
    payload = {"v": _LOCALIZATION_SIG_VERSION, **descriptor}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def localization_model_signature_from_config_path(
    config_path: Path,
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, str]]]:
    if not config_path.is_file():
        return None, None, None
    try:
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError:
        return None, None, None
    if not isinstance(raw, dict):
        return None, None, None
    try:
        descriptor = localization_model_descriptor_from_config(raw)
    except ValueError:
        return None, None, None
    if not descriptor["feature_conf"] or not descriptor["matcher_conf"]:
        return None, None, None
    sig = localization_model_signature_from_descriptor(descriptor)
    return sig, None, descriptor