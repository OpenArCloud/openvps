# Copyright 2026 Nokia
# Licensed under the MIT License
# SPDX-License-Identifier: MIT
#
# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


from datetime import datetime, timezone
import json
import uuid
from typing import Any, List, Optional

from oscp.geopose import GeoPose
from oscp.spatialdds_types import (
    CoordConvention,
    CoordScale,
    CovMatrix,
    FrameRef,
    FramedPose,
    MetaKV,
    PoseSE3,
    QuaternionXYZW,
    Time,
    Vec3,
)

from oscp.geoposeprotocol import (
    GeoPoseAccuracy,
    GeoPoseRequest,
    GeoPoseResponse,
    Sensor,
    SensorReadings,
    _timestamp_ms_from_json,
)


def _protocol_json_default(o: Any) -> Any:
    """json.dumps default= for OSCP objects plus SpatialDDS extension types."""
    if isinstance(o, Time):
        return o.to_json_dict()
    if isinstance(o, FramedPose):
        return o.to_json_dict()
    if isinstance(o, CovMatrix):
        return o.to_json_dict()
    if isinstance(o, PoseSE3):
        return o.to_json_dict()
    if isinstance(o, FrameRef):
        return o.to_json_dict()
    if isinstance(o, CoordScale):
        return o.to_json_dict()
    if isinstance(o, CoordConvention):
        return o.value
    if isinstance(o, MetaKV):
        return o.to_json_dict()
    if isinstance(o, Vec3):
        return o.to_json_dict()
    if isinstance(o, QuaternionXYZW):
        return o.to_json_dict()
    if isinstance(o, GeoPose):
        return {
            "position": {
                "lat": o.position.lat,
                "lon": o.position.lon,
                "h": o.position.h,
            },
            "quaternion": {
                "x": o.quaternion.x,
                "y": o.quaternion.y,
                "z": o.quaternion.z,
                "w": o.quaternion.w,
            },
        }
    return o.__dict__


class GeoPoseResponseExtended(GeoPoseResponse):
    """
    OSCP GeoPoseResponse extended with SpatialDDS-style time and metric poses.
    Wire format adds optional keys: time {sec, nanosec}, poses (array of
    FramedPose: pose, frame_ref, cov, stamp
    The same physical pose may appear in multiple coordinate frames when the VPS
    exposes several maps or a frame hierarchy. See https://spatialdds.org/ for more details.
    """

    def __init__(
        self,
        type:str = None,
        id:str = None,
        timestamp:int = None,
        accuracy: GeoPoseAccuracy = None,
        geopose: GeoPose = None,
        time: Optional[Time] = None,
        poses: Optional[List[FramedPose]] = None,
        geoposes: Optional[List[GeoPose]] = None,
    ):
        if type is None:
            type = "geopose"
        if id is None:
            id = str(uuid.uuid4())
        if timestamp is None:
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000) # The number of milliseconds since the Unix Epoch.
        if accuracy is None:
            accuracy = GeoPoseAccuracy()
        if geopose is None:
            geopose = GeoPose()
        super().__init__(type=type, id=id, timestamp=timestamp, accuracy=accuracy, geopose=geopose)

        if time is None:
            time = Time.from_unix_millis(timestamp)
        self.time = time
        if poses is None:
            poses = []
        self.poses = poses
        if geoposes is None:
            geoposes = []
        self.geoposes = geoposes

    def __str__(self):
        return "{" + \
            "type:" + str(self.type) + ',' + \
            "id:" + str(self.id) + ',' + \
            "timestamp:" + str(self.timestamp) + ',' + \
            "accuracy:" + str(self.accuracy) + ',' + \
            "geopose:" + str(self.geopose) + ',' + \
            "time:" + str(self.time) + ',' + \
            "poses:" + str(self.poses) + ',' + \
            "geoposes:" + str(self.geoposes) + \
        "}"

    def toJson(self):
        return json.dumps(self, default=_protocol_json_default)

    def to_json_dict(self):
        return json.loads(self.toJson())

    @staticmethod
    def fromJson(jdata):
        accuracy = GeoPoseAccuracy.fromJson(jdata["accuracy"])
        geopose = GeoPose.fromJson(jdata["geopose"])
        time = None
        if "time" in jdata and jdata["time"] is not None:
            time = Time.from_json(jdata["time"])
        poses = None
        if "poses" in jdata and jdata["poses"] is not None:
            raw = jdata["poses"]
            if not isinstance(raw, list):
                raise TypeError("poses must be a JSON array of FramedPose objects")
            poses = [FramedPose.from_json(item) for item in raw]
        geoposes = None
        if "geoposes" in jdata and jdata["geoposes"] is not None:
            raw_g = jdata["geoposes"]
            if not isinstance(raw_g, list):
                raise TypeError("geoposes must be a JSON array of GeoPose objects")
            geoposes = [GeoPose.fromJson(item) for item in raw_g]
        return GeoPoseResponseExtended(
            type=jdata["type"],
            id=jdata["id"],
            timestamp=_timestamp_ms_from_json(jdata["timestamp"]),
            accuracy=accuracy,
            geopose=geopose,
            time=time,
            poses=poses,
            geoposes=geoposes,
        )


class GeoPoseRequestExtended(GeoPoseRequest):
    """
    GeoPoseRequest with optional SpatialDDS-style ``time`` (sec + nanosec) alongside
    legacy ``timestamp`` (ms), and ``priorPoses`` as GeoPoseResponseExtended entries
    (optional ``time`` and ``poses`` on each prior response).
    """
    def __init__(
        self,
        type: str = None,
        id: str = None,
        timestamp: int = None,
        sensors: Optional[List[Sensor]] = None,
        sensorReadings: SensorReadings = None,
        priorPoses: Optional[List[GeoPoseResponseExtended]] = None,
        time: Optional[Time] = None,
    ):
        if type is None:
            type = "geopose"
        if id is None:
            id = str(uuid.uuid4())
        if timestamp is None:
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000) # The number of milliseconds since the Unix Epoch.
        if sensors is None:
            sensors = []
        if sensorReadings is None:
            sensorReadings = SensorReadings()
        if priorPoses is None:
            priorPoses = []  # [optional] of type GeoPoseResponseExtended

        super().__init__(type=type, id=id, timestamp=timestamp, sensors=sensors, sensorReadings=sensorReadings, priorPoses=priorPoses)

        if time is None:
            time = Time.from_unix_millis(self.timestamp)
        self.time = time

    def __str__(self):
        return "{" + \
            "type:" + str(self.type) + ',' + \
            "id:" + str(self.id) + ',' + \
            "timestamp:" + str(self.timestamp) + ',' + \
            "time:" + str(self.time) + ',' + \
            "sensors:" + str(self.sensors) + ',' + \
            "sensorReadings:" + str(self.sensorReadings) + ',' + \
            "priorPoses:" + str(self.priorPoses) + \
        "}"

    def toJson(self):
        return json.dumps(self, default=_protocol_json_default)

    @staticmethod
    def fromJson(jdata):
        sensors = []
        for jsensor in jdata["sensors"]:
            sensors.append(Sensor.fromJson(jsensor))
        sensorReadings = SensorReadings.fromJson(jdata["sensorReadings"])
        prior_poses: List[GeoPoseResponseExtended] = []
        if "priorPoses" in jdata:
            for jprior_pose in jdata["priorPoses"]:
                prior_poses.append(GeoPoseResponseExtended.fromJson(jprior_pose))
        time = None
        if "time" in jdata and jdata["time"] is not None:
            time = Time.from_json(jdata["time"])
        return GeoPoseRequestExtended(
            type=jdata["type"],
            id=jdata["id"],
            timestamp=_timestamp_ms_from_json(jdata["timestamp"]),
            sensors=sensors,
            sensorReadings=sensorReadings,
            priorPoses=prior_poses,
            time=time,
        )
