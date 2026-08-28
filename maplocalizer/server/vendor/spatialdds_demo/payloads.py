"""
Canonical payload builders for the spec types more than one process emits.

Every function returns a dict that ``json_mapping.from_json`` builds into its
IDL type — a *complete* one: the spec has no absent fields, only values whose
``has_*`` flag says whether to read them, so a builder that omits a field
produces something that is not its type.

This module exists because the demo learned the cost of not having it. The
multi-operator publishers and the ROS 2 bridge each grew their own idea of
what a `Detection3D` looks like, and both were wrong in different ways — the
ROS 2 one had never once emitted a valid one, with a green test suite,
because its tests asserted against the same invented shape its encoder
produced. Nothing compared either to the IDL.

Two conventions the IDL enforces and these follow:

* **Vectors are arrays.** ``Vec3`` is ``double[3]``, so ``t`` is
  ``[x, y, z]``. ``_vec`` accepts the ``{"x": …}`` form callers often have.
* **Optionals are presence-flagged**, never omitted and never null.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Dict, List, Sequence

SCHEMA_CORE = "spatial.core/1.7"
SCHEMA_SEMANTICS = "spatial.semantics/1.7"
SCHEMA_EVENTS = "spatial.events/1.7"
SCHEMA_DISCOVERY = "spatial.discovery/1.7"

COV_NONE = {"discriminator": "COV_NONE", "none": 0}


def stamp(timestamp_s: float) -> Dict[str, int]:
    """Float epoch seconds as a ``builtin::Time``."""
    sec = int(timestamp_s)
    nsec = int(round((timestamp_s - sec) * 1_000_000_000))
    if nsec >= 1_000_000_000:
        sec += 1
        nsec -= 1_000_000_000
    elif nsec < 0:
        sec -= 1
        nsec += 1_000_000_000
    return {"sec": sec, "nanosec": nsec}


def vec(value, keys: Sequence[str] = ("x", "y", "z"),
        default: float = 0.0) -> List[float]:
    """
    Normalise a vector to the IDL array form.

    ``Vec3`` and ``QuaternionXYZW`` are arrays, but much of this demo builds
    them as ``{"x": …, "y": …}`` objects. Accept either so callers need not
    care which they hold.
    """
    if isinstance(value, dict):
        return [float(value.get(k, 1.0 if k == "w" else default)) for k in keys]
    return [float(v) for v in value]


def frame_ref(fqn: str, uuid: str = "",
              coord_convention: str = "ENU") -> Dict[str, object]:
    """
    A complete ``FrameRef``.

    The UUID is a deterministic UUIDv5 of the FQN when none is given, so the
    same frame gets the same id across processes and runs. ENU is 1.7's
    default convention and REP-103's, and stating it beats leaving it unsaid.
    """
    return {
        "uuid": uuid or str(_uuid.uuid5(_uuid.NAMESPACE_URL, fqn)),
        "fqn": fqn,
        "has_coord_convention": True,
        "coord_convention": coord_convention,
    }


def framed_pose(x: float, y: float, z: float, q: Sequence[float],
                frame_ref_fqn: str, timestamp_s: float) -> Dict:
    """
    A ``spatial::core::FramedPose`` — a pose plus the frame it means
    something in.

    Note what it does not carry: velocity, or a source operator. The demo's
    old ego payload had both. Velocity was never read by any consumer, and
    the operator is already in the topic name, which is where DDS expects
    that kind of identity to live.
    """
    return {
        "pose": {"t": [float(x), float(y), float(z)],
                 "q": vec(q, ("x", "y", "z", "w"))},
        "frame_ref": frame_ref(frame_ref_fqn),
        "cov": dict(COV_NONE),
        "stamp": stamp(timestamp_s),
    }


def detection3d(det_id: str, class_id: str, score: float,
                center: Sequence[float], size: Sequence[float],
                q: Sequence[float], frame_ref_fqn: str,
                timestamp_s: float, source_id: str,
                frame_ref_dict: Dict = None,
                velocity: Sequence[float] = None) -> Dict:
    """
    One complete ``spatial::semantics::Detection3D``.

    ``frame_ref_dict`` lets a caller that already has a FrameRef — the ROS 2
    bridge, which maps tf2 frame_ids — pass it instead of an FQN.

    ``velocity=None`` sets the presence flag false rather than passing a zero
    vector off as a measurement. A source that genuinely has no velocity —
    ROS 2's Detection3DArray, for one — says so.
    """
    return {
        "det_id": str(det_id),
        "frame_ref": frame_ref_dict or frame_ref(frame_ref_fqn),
        "has_tile": False,
        # spatial::core::TileKey is (x, y, z, level) — no map_id. The map a
        # tile belongs to is context, not part of the key.
        "tile_key": {"level": 0, "x": 0, "y": 0, "z": 0},
        "class_id": str(class_id),
        "score": float(score),
        "center": vec(center),
        "size": vec(size),
        "q": vec(q, ("x", "y", "z", "w")),
        "has_covariance": False,
        "cov_pos": [0.0] * 9,
        "cov_rot": [0.0] * 9,
        "has_track_id": False,
        "track_id": "",
        "stamp": stamp(timestamp_s),
        "source_id": str(source_id),
        "has_attributes": False,
        # MetaKV carries typed `entries` (a sequence of common::KV) as well
        # as its JSON string now, so the extension hatch no longer forces
        # JSON back onto the bus. Nothing here needs it, so it stays empty.
        "attributes": [],
        "has_visibility": False,
        "visibility": 0.0,
        "has_num_pts": False,
        "num_lidar_pts": 0,
        "num_radar_pts": 0,
        # Added to Detection3D in 1.7's findings-batch-2 revision. The demo
        # used to compose `oarc_demo::DetectionWithVelocity` around this type
        # purely to add these two fields.
        "has_velocity": velocity is not None,
        "velocity": vec(velocity if velocity is not None else (0.0, 0.0, 0.0)),
    }


def detection_set(set_id: str, source_operator: str, frame_ref_fqn: str,
                  dets: Sequence[Dict], frame_seq: int,
                  timestamp_s: float, frame_ref_dict: Dict = None) -> Dict:
    """
    A complete ``spatial::semantics::Detection3DSet``.

    The operator is `source_id`, which is the type's own field for it — the
    demo used to wrap this in `Detection3DSet` to add a
    `source_operator`. `frame_seq` has no home on the type and is dropped:
    the set is identified by `set_id` and ordered by `stamp`.
    """
    return {
        "set_id": str(set_id),
        "frame_ref": frame_ref_dict or frame_ref(frame_ref_fqn),
        "has_tile": False,
        "tile_key": {"level": 0, "x": 0, "y": 0, "z": 0},
        "dets": list(dets),
        "stamp": stamp(timestamp_s),
        "source_id": str(source_operator),
    }
