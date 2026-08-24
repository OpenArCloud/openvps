# Copyright 2026 Nokia
# Licensed under the MIT License
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)
#
# SpatialDDS-aligned types for JSON extension to OSCP GeoPose responses.
# IDL reference: SpatialDDS 1.6 Core / spatial::common (CovarianceType, FrameRef),
# spatial::core (PoseSE3, FramedPose, CovMatrix).
# https://spatialdds.org/SpatialDDS-1.6-full/


from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union

Number = Union[int, float]


class CovarianceType(str, Enum):
    """SpatialDDS spatial::common::CovarianceType (string names for JSON)."""

    COV_NONE = "COV_NONE"
    COV_POS3 = "COV_POS3"
    COV_POSE6 = "COV_POSE6"
    COV_ROT3 = "COV_ROT3"
    COV_POSE6_TWIST6 = "COV_POSE6_TWIST6"

    @property
    def numeric(self) -> int:
        return COVARIANCE_TYPE_NUMERIC[self]


COVARIANCE_TYPE_NUMERIC: dict[CovarianceType, int] = {
    CovarianceType.COV_NONE: 0,
    CovarianceType.COV_POS3: 3,
    CovarianceType.COV_POSE6: 6,
    CovarianceType.COV_ROT3: 9,
    CovarianceType.COV_POSE6_TWIST6: 12,
}


def covariance_type_from_json(value: str) -> CovarianceType:
    return CovarianceType(value)


class CoordConvention(str, Enum):
    """SpatialDDS 1.6 spatial::common::CoordConvention (JSON = IDL identifier strings)."""

    ENU = "ENU"
    CV = "CV"
    GRAPHICS = "GRAPHICS"
    UNITY_LH = "UNITY_LH"
    NED = "NED"
    OTHER = "OTHER"


class CoordScaleTargetUnit(str, Enum):
    """Target unit for FrameRef.coord_scale.scale_factor (extensible)."""

    SI_METER = "SI_METER"


class CoordScale(object):
    """Linear scale from frame numeric units to target_unit (see target_unit semantics)."""

    def __init__(self, target_unit: CoordScaleTargetUnit, scale_factor: float):
        self.target_unit = target_unit
        self.scale_factor = float(scale_factor)

    def to_json_dict(self) -> dict[str, Union[str, float]]:
        return {"target_unit": self.target_unit.value, "scale_factor": self.scale_factor}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "CoordScale":
        return CoordScale(
            target_unit=CoordScaleTargetUnit(str(jdata["target_unit"])),
            scale_factor=float(jdata["scale_factor"]),
        )


class MetaKV(object):
    """SpatialDDS spatial::common::MetaKV - json is a JSON object serialized as a string."""

    def __init__(self, namespace: str, json_payload: str):
        self.namespace = str(namespace)
        self.json_payload = str(json_payload)

    def to_json_dict(self) -> dict[str, str]:
        return {"namespace": self.namespace, "json": self.json_payload}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "MetaKV":
        return MetaKV(namespace=str(jdata["namespace"]), json_payload=str(jdata["json"]))


class Time(object):
    """builtin::Time / spatial::core::Time: UTC sec + nanosec."""

    def __init__(self, sec: int = 0, nanosec: int = 0):
        self.sec = int(sec)
        self.nanosec = int(nanosec)

    def __repr__(self) -> str:
        return f"Time(sec={self.sec}, nanosec={self.nanosec})"

    def __str__(self) -> str:
        return f"{{sec:{self.sec}, nanosec:{self.nanosec}}}"

    def to_json_dict(self) -> dict[str, int]:
        return {"sec": self.sec, "nanosec": self.nanosec}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "Time":
        return Time(sec=int(jdata["sec"]), nanosec=int(jdata["nanosec"]))

    @staticmethod
    def from_unix_millis(ms: Number) -> "Time":
        ms_f = float(ms)
        sec = int(ms_f // 1000)
        nanosec = int(round((ms_f - sec * 1000) * 1_000_000))
        if nanosec >= 1_000_000_000:
            sec += 1
            nanosec -= 1_000_000_000
        return Time(sec=sec, nanosec=nanosec)


class FrameRef(object):
    def __init__(
        self,
        uuid: str,
        fqn: str,
        has_coord_convention: bool = False,
        coord_convention: CoordConvention = CoordConvention.ENU,
        has_coord_scale: bool = False,
        coord_scale: Optional[CoordScale] = None,
        meta_kv: Optional[list[MetaKV]] = None,
    ):
        self.uuid = str(uuid)
        self.fqn = str(fqn)
        self.has_coord_convention = bool(has_coord_convention)
        self.coord_convention = coord_convention
        self.has_coord_scale = bool(has_coord_scale)
        self.coord_scale = coord_scale
        self.meta_kv = meta_kv if meta_kv is not None else None

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"uuid": self.uuid, "fqn": self.fqn}
        if self.has_coord_convention:
            d["has_coord_convention"] = True
            d["coord_convention"] = self.coord_convention.value
        if self.has_coord_scale and self.coord_scale is not None:
            d["has_coord_scale"] = True
            d["coord_scale"] = self.coord_scale.to_json_dict()
        if self.meta_kv:
            d["meta_kv"] = [m.to_json_dict() for m in self.meta_kv]
        return d

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "FrameRef":
        has_cc = bool(jdata.get("has_coord_convention", False))
        cc = CoordConvention(str(jdata["coord_convention"])) if has_cc else CoordConvention.ENU
        has_cs = bool(jdata.get("has_coord_scale", False))
        cs: Optional[CoordScale] = None
        if has_cs:
            raw_cs = jdata.get("coord_scale")
            if raw_cs is None:
                raise KeyError("coord_scale required when has_coord_scale is true")
            cs = CoordScale.from_json(raw_cs)
        meta: Optional[list[MetaKV]] = None
        raw_meta = jdata.get("meta_kv")
        if raw_meta is not None:
            if not isinstance(raw_meta, list):
                raise TypeError("meta_kv must be a list")
            meta = [MetaKV.from_json(m) for m in raw_meta]
        return FrameRef(
            uuid=str(jdata["uuid"]),
            fqn=str(jdata["fqn"]),
            has_coord_convention=has_cc,
            coord_convention=cc,
            has_coord_scale=has_cs,
            coord_scale=cs,
            meta_kv=meta,
        )


class Vec3(object):
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def to_json_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "Vec3":
        return Vec3(x=jdata["x"], y=jdata["y"], z=jdata["z"])


class QuaternionXYZW(object):
    """Quaternion (x, y, z, w) in GeoPose / SpatialDDS order."""

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, w: float = 1.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.w = float(w)

    def to_json_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "QuaternionXYZW":
        return QuaternionXYZW(x=jdata["x"], y=jdata["y"], z=jdata["z"], w=jdata["w"])


class PoseSE3(object):
    def __init__(self, t: Optional[Vec3] = None, q: Optional[QuaternionXYZW] = None):
        self.t = t if t is not None else Vec3()
        self.q = q if q is not None else QuaternionXYZW()

    def to_json_dict(self) -> dict[str, Any]:
        return {"t": self.t.to_json_dict(), "q": self.q.to_json_dict()}

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "PoseSE3":
        return PoseSE3(t=Vec3.from_json(jdata["t"]), q=QuaternionXYZW.from_json(jdata["q"]))


class CovMatrix(object):
    """
    JSON discriminated union mirroring SpatialDDS union CovMatrix.
    Wire keys use underscores (SpatialDDS JSON). Payload keys: pos, pose, rot, pose_twist.
    """

    def __init__(
        self,
        covariance_type: CovarianceType = CovarianceType.COV_NONE,
        pos: Optional[Sequence[Number]] = None,
        pose: Optional[Sequence[Number]] = None,
        rot: Optional[Sequence[Number]] = None,
        pose_twist: Optional[Sequence[Number]] = None,
    ):
        self.covariance_type = covariance_type
        self.pos = list(pos) if pos is not None else None
        self.pose = list(pose) if pose is not None else None
        self.rot = list(rot) if rot is not None else None
        self.pose_twist = list(pose_twist) if pose_twist is not None else None

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"covariance_type": self.covariance_type.value}
        if self.covariance_type == CovarianceType.COV_POS3 and self.pos is not None:
            d["pos"] = [float(x) for x in self.pos]
        elif self.covariance_type == CovarianceType.COV_POSE6 and self.pose is not None:
            d["pose"] = [float(x) for x in self.pose]
        elif self.covariance_type == CovarianceType.COV_ROT3 and self.rot is not None:
            d["rot"] = [float(x) for x in self.rot]
        elif self.covariance_type == CovarianceType.COV_POSE6_TWIST6 and self.pose_twist is not None:
            d["pose_twist"] = [float(x) for x in self.pose_twist]
        return d

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "CovMatrix":
        ct = covariance_type_from_json(str(jdata["covariance_type"]))
        return CovMatrix(
            covariance_type=ct,
            pos=jdata.get("pos"),
            pose=jdata.get("pose"),
            rot=jdata.get("rot"),
            pose_twist=jdata.get("pose_twist"),
        )


class FramedPose(object):
    def __init__(
        self,
        pose: Optional[PoseSE3] = None,
        frame_ref: Optional[FrameRef] = None,
        cov: Optional[CovMatrix] = None,
        stamp: Optional[Time] = None,
    ):
        self.pose = pose if pose is not None else PoseSE3()
        self.frame_ref = frame_ref if frame_ref is not None else FrameRef(uuid="", fqn="")
        self.cov = cov if cov is not None else CovMatrix()
        self.stamp = stamp if stamp is not None else Time()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "pose": self.pose.to_json_dict(),
            "frame_ref": self.frame_ref.to_json_dict(),
            "cov": self.cov.to_json_dict(),
            "stamp": self.stamp.to_json_dict(),
        }

    @staticmethod
    def from_json(jdata: Mapping[str, Any]) -> "FramedPose":
        if "frame_ref" not in jdata:
            raise KeyError("frame_ref")
        return FramedPose(
            pose=PoseSE3.from_json(jdata["pose"]),
            frame_ref=FrameRef.from_json(jdata["frame_ref"]),
            cov=CovMatrix.from_json(jdata["cov"]),
            stamp=Time.from_json(jdata["stamp"]),
        )


def json_default(obj: Any) -> Any:
    """json.dumps default= for nested spatial types (if used standalone)."""
    if isinstance(obj, Time):
        return obj.to_json_dict()
    if isinstance(obj, FrameRef):
        return obj.to_json_dict()
    if isinstance(obj, Vec3):
        return obj.to_json_dict()
    if isinstance(obj, QuaternionXYZW):
        return obj.to_json_dict()
    if isinstance(obj, PoseSE3):
        return obj.to_json_dict()
    if isinstance(obj, CovMatrix):
        return obj.to_json_dict()
    if isinstance(obj, FramedPose):
        return obj.to_json_dict()
    if isinstance(obj, CoordScale):
        return obj.to_json_dict()
    if isinstance(obj, MetaKV):
        return obj.to_json_dict()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
