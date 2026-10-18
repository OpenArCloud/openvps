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

**Scale is now a wire field.** SpatialDDS 1.8 gives `FrameRef` four members for it —
`has_scale`, `scale_status`, `meters_per_unit`, `display_unit` — so the `openvps.frame`
MetaKV convention that stood in for them is gone. The previous version of this module said
that when the field arrived this would become a deletion rather than an excavation, and it
did.

Worth recording why the deletion loses nothing: the convention never reached the wire. Its
only caller discarded the MetaKV it built (`idl_frame, _meta = frame_ref_to_idl(...)`), so
every `FramedPose` this service ever published carried a frame that said nothing about its
units. The announce hint `openvps.coord_scale_m_per_unit` was the only carrier that
worked, and it still is for discovery — `Announce` has no `FrameRef` for a service's own
map frame, only `coverage_frame_ref` for the frame coverage is evaluated in. So the hint
stays; what changes is that a response now states its own units.

**`has_scale = false` is a claim, not a default.** 1.8 reads an unset `has_scale` as
"this frame is metric, 1 unit = 1 metre", which is correct for every pre-1.8 publisher and
wrong for every OpenVPS map: a COLMAP frame is gauge-free and its scale is recovered after
the fact — 0.2417 m/unit on the sample scan. A producer that has not established the scale
must say so with `SCALE_UNKNOWN`; absence is not the unknown state. So the quartet is
always set explicitly here, and never left to default.
"""

from __future__ import annotations

from typing import Optional

from oscp.spatialdds_types import (
    CoordConvention as JsonCoordConvention,
    FrameRef as JsonFrameRef,
    FramedPose as JsonFramedPose,
)

from spatialdds_idl18.spatial.common import (
    CoordConvention as IdlCoordConvention,
    FrameRef as IdlFrameRef,
    ScaleStatus as IdlScaleStatus,
)
from spatialdds_demo.json_mapping import from_json
from spatialdds_demo.payloads import COV_NONE
from spatialdds_idl18.spatial.core import (
    CovMatrix as IdlCovMatrix,
    FramedPose as IdlFramedPose,
    PoseSE3 as IdlPoseSE3,
)
from spatialdds_idl18.builtin import Time as IdlTime

# `display_unit` is presentation only — 1.8 says it is never used for computation, so
# `meters_per_unit` is the single source of truth and this is a label beside it.
DISPLAY_UNIT_METRE = "m"

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
    The wire `FrameRef`, with scale stated natively.

    `has_coord_convention` is set explicitly even when the value is the ENU default: §2.12
    asks producers to say so rather than rely on the default, and the localizer always knows
    which convention its map frame uses. The scale quartet is set for the same reason and a
    stronger one — see the module docstring on `has_scale` being a claim.

    `scale_status` distinguishes a scale the producer asserts from one recovered from a
    similarity transform, which is a distinction the loader already makes and previously had
    nowhere to put: `MapTransformInfo.from_transform_json` takes the value from
    `frame_ref.coord_scale` when the file carries one and otherwise takes the norm of the
    map-to-ENU matrix. The first is `SCALE_DECLARED`, the second is `SCALE_DERIVED` — the
    spec's own gloss for it is "recovered (e.g. from a legacy similarity transform)", which
    is exactly what that norm is.
    """
    if fr.has_coord_scale and fr.coord_scale is not None:
        has_scale = True
        scale_status = (IdlScaleStatus.SCALE_DECLARED if fr.coord_scale_declared
                        else IdlScaleStatus.SCALE_DERIVED)
        meters_per_unit = float(fr.coord_scale.scale_factor)
        display_unit = DISPLAY_UNIT_METRE
    else:
        # Not established. `has_scale` still true, because false would assert metric.
        has_scale = True
        scale_status = IdlScaleStatus.SCALE_UNKNOWN
        meters_per_unit = 0.0
        display_unit = ""

    return IdlFrameRef(
        uuid=str(fr.uuid),
        fqn=str(fr.fqn),
        has_coord_convention=True,
        coord_convention=convention_to_idl(
            fr.coord_convention if fr.has_coord_convention else JsonCoordConvention.ENU
        ),
        has_scale=has_scale,
        scale_status=scale_status,
        meters_per_unit=meters_per_unit,
        display_unit=display_unit,
    )


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
    it. The units are declared on the frame instead, which under 1.8 is somewhere a consumer
    can actually read them.
    """
    return IdlFramedPose(
        pose=IdlPoseSE3(
            t=[float(fp.pose.t.x), float(fp.pose.t.y), float(fp.pose.t.z)],
            q=[float(fp.pose.q.x), float(fp.pose.q.y), float(fp.pose.q.z), float(fp.pose.q.w)],
        ),
        frame_ref=frame_ref_to_idl(fp.frame_ref),
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
