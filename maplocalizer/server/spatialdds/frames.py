# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
"""
Convert the localizer's frame and pose objects to their SpatialDDS wire types.

The localizer already speaks SpatialDDS shapes: `oscp/spatialdds_types.py` defines
`FrameRef`, `FramedPose`, `PoseSE3` and friends as plain Python, and the HTTP path
serialises them to JSON. Those are the internal representation, and this module is the only
place that turns them into the generated IDL bindings. Keeping the conversion in one file is
deliberate — two independent definitions of `FramedPose` in one process is how they drift.

**coord_scale.** `FrameRef.coord_scale` is upstream's proposal for declaring what a frame's
units are; it is not in SpatialDDS 1.6, 1.7 or 1.8, so the generated `FrameRef` has no field
for it. Until it lands it rides as a `MetaKV` entry under the `openvps.frame` namespace,
which §2.13's typed-first rule permits for exactly this case. `SCALE_NAMESPACE` and
`frame_ref_to_idl` are the whole of it: when the field exists natively, this becomes a
deletion rather than an excavation.

Dropping it instead was the alternative and is not acceptable. OpenVPS map frames are not
metric — a reconstruction from images alone is gauge-free, and the scale is recovered later
— so a `FramedPose` published without its scale is a plausible pose wrong by a constant
factor, with nothing on the wire to say so.
"""

from __future__ import annotations

import json
from typing import Optional

from oscp.spatialdds_types import (
    CoordConvention as JsonCoordConvention,
    FrameRef as JsonFrameRef,
    FramedPose as JsonFramedPose,
)

from spatialdds_idl.spatial.common import (
    CoordConvention as IdlCoordConvention,
    FrameRef as IdlFrameRef,
    KV,
    MetaKV,
)
from spatialdds_demo.json_mapping import from_json
from spatialdds_demo.payloads import COV_NONE
from spatialdds_idl.spatial.core import (
    CovMatrix as IdlCovMatrix,
    FramedPose as IdlFramedPose,
    PoseSE3 as IdlPoseSE3,
)
from spatialdds_idl.builtin import Time as IdlTime

# Where the scale rides until the spec has a field for it. Namespaced per the typed-first
# extension rule; `entries` rather than `json` so it stays inspectable without parsing.
SCALE_NAMESPACE = "openvps.frame"

_CONVENTION = {
    JsonCoordConvention.ENU: IdlCoordConvention.ENU,
    JsonCoordConvention.CV: IdlCoordConvention.CV,
    JsonCoordConvention.GRAPHICS: IdlCoordConvention.GRAPHICS,
    JsonCoordConvention.UNITY_LH: IdlCoordConvention.UNITY_LH,
    JsonCoordConvention.NED: IdlCoordConvention.NED,
    JsonCoordConvention.OTHER: IdlCoordConvention.OTHER,
}


def convention_to_idl(c: JsonCoordConvention) -> IdlCoordConvention:
    return _CONVENTION[c]


def frame_ref_to_idl(fr: JsonFrameRef) -> IdlFrameRef:
    """
    The wire `FrameRef`, with the scale carried as MetaKV.

    `has_coord_convention` is set explicitly even when the value is the ENU default: §2.12
    asks producers to say so rather than rely on the default, and the localizer always knows
    which convention its map frame uses.
    """
    meta = []
    if fr.has_coord_scale and fr.coord_scale is not None:
        meta.append(
            MetaKV(
                namespace=SCALE_NAMESPACE,
                json=json.dumps(fr.coord_scale.to_json_dict(), separators=(",", ":")),
                entries=[
                    KV(key="coord_scale.target_unit", value=str(fr.coord_scale.target_unit.value)),
                    KV(key="coord_scale.scale_factor", value=repr(float(fr.coord_scale.scale_factor))),
                ],
            )
        )
    return IdlFrameRef(
        uuid=str(fr.uuid),
        fqn=str(fr.fqn),
        has_coord_convention=True,
        coord_convention=convention_to_idl(
            fr.coord_convention if fr.has_coord_convention else JsonCoordConvention.ENU
        ),
    ), meta


def scale_factor_of(fr: JsonFrameRef) -> Optional[float]:
    """Metres per frame unit, or None when the frame does not declare it."""
    if fr.has_coord_scale and fr.coord_scale is not None:
        return float(fr.coord_scale.scale_factor)
    return None


def framed_pose_to_idl(fp: JsonFramedPose, stamp: IdlTime) -> IdlFramedPose:
    """
    A wire `FramedPose`, translation untouched.

    The translation stays in the map's own units. It is *not* pre-multiplied by the scale
    factor: doing that would make the poses inconsistent with the map's own geometry — point
    clouds, meshes, tiles are all in map units — which moves the problem rather than solving
    it. The units are declared on the frame instead; see the module docstring.
    """
    idl_frame, _meta = frame_ref_to_idl(fp.frame_ref)
    return IdlFramedPose(
        pose=IdlPoseSE3(
            t=[float(fp.pose.t.x), float(fp.pose.t.y), float(fp.pose.t.z)],
            q=[float(fp.pose.q.x), float(fp.pose.q.y), float(fp.pose.q.z), float(fp.pose.q.w)],
        ),
        frame_ref=idl_frame,
        cov=_cov_none(),
        stamp=stamp,
    )


def _cov_none() -> IdlCovMatrix:
    """
    `COV_NONE`. The PnP step surfaces no covariance, so inventing one would be worse — a
    plausible invented uncertainty is worse than a declared absence, because nothing
    downstream can tell it was invented.

    Built through the demo's `from_json` rather than by calling the union constructor: the
    generated union takes keyword arguments only, and `from_json` refuses a case name the
    union does not have, which a hand-built one would accept silently.
    """
    return from_json(IdlCovMatrix, dict(COV_NONE))
