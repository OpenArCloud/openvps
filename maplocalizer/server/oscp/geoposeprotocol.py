# Open AR Cloud GeoPoseProtocol - Python implementation
# Created by Gabor Soros, 2023
#
# Copyright 2023 Nokia
# Licensed under the MIT License
# SPDX-License-Identifier: MIT
#
# Created based on the protocol definition:
# https://github.com/OpenArCloud/oscp-geopose-protocol
# and the JavaScript implementation:
# https://github.com/OpenArCloud/gpp-access/

from datetime import datetime, timezone
from enum import Enum
import uuid
import json
from oscp.geopose import *
import sys
import re

'''
Sensor types usable with the GeoPose protocol
Use when creating a new Sensor object.
'''
class SensorType(str, Enum):
    CAMERA = 'camera'
    GEOLOCATION = 'geolocation'
    WIFI = 'wifi'
    BLUETOOTH = 'bluetooth'
    ACCELEROMETER = 'accelerometer'
    GYROSCOPE = 'gyroscope'
    MAGNETOMETER = 'magnetometer'
    UNKNOWN = 'unknown'
    # TODO: add altitude sensor

    @staticmethod
    def fromJson(jdata):
        if jdata in ('CAMERA', 'camera'):
            return SensorType.CAMERA
        elif jdata in ('GEOLOCATION', 'geolocation'):
            return SensorType.GEOLOCATION
        elif jdata in ('WIFI', 'wifi'):
            return SensorType.WIFI
        elif jdata in ('BLUETOOTH', 'bluetooth'):
            return SensorType.BLUETOOTH
        elif jdata in ('ACCELEROMETER', 'accelerometer'):
            return SensorType.ACCELEROMETER
        elif jdata in ('GYROSCOPE', 'gyroscope'):
            return SensorType.GYROSCOPE
        elif jdata in ('MAGNETOMETER', 'magnetometer'):
            return SensorType.MAGNETOMETER
        elif jdata in ('UNKNOWN', 'unknown'):
            return SensorType.UNKNOWN
        else:
            raise NotImplementedError

'''
Image formats usable with the CameraReading object
Use when creating a SensorReading object for a new Sensor of type 'camera'.
'''
class ImageFormat(str, Enum):
    RGBA32 = 'RGBA32'
    GRAY8 = 'GRAY8'
    DEPTH = 'DEPTH'
    JPG = 'JPG'
    UNKNOWN = 'unknown'

    @staticmethod
    def fromJson(jdata):
        if jdata in ('RGBA32', 'rgba32'):
            return ImageFormat.RGBA32
        elif jdata in ('GRAY8', 'gray8'):
            return ImageFormat.GRAY8
        elif jdata in ('DEPTH', 'depth'):
            return ImageFormat.DEPTH
        elif jdata in ('JPG', 'jpg'):
            return ImageFormat.JPG
        elif jdata in ('UNKNOWN', 'unknown'):
            return ImageFormat.UNKNOWN
        else:
            raise NotImplementedError

class ImageOrientation(object):
    def __init__(self, mirrored = False, rotation = 0.0):
        self.mirrored = mirrored
        self.rotation = rotation

    def __str__(self):
        return "{" + \
            "mirrored:" + str(self.mirrored) + "," + \
            "rotation:" + str(self.rotation) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return ImageOrientation(**jdata)

# The camera models of Colmap are used here
# See https://colmap.github.io/cameras.html
class CameraModel(str, Enum):
    SIMPLE_PINHOLE = 'SIMPLE_PINHOLE' # f, cx, cy
    PINHOLE = 'PINHOLE' # fx, fy, cx, cy
    SIMPLE_RADIAL = 'SIMPLE_RADIAL' # f, cx, cy, k
    RADIAL = 'RADIAL' # f, cx, cy, k1, k2
    OPENCV = 'OPENCV' # fx, fy, cx, cy, k1, k2, p1, p2
    OPENCV_FISHEYE = 'OPENCV_FISHEYE' # fx, fy, cx, cy, k1, k2, k3, k4
    FULL_OPENCV = 'FULL_OPENCV' # fx, fy, cx, cy, k1, k2, p1, p2, k3, k4, k5, k6
    FOV = 'FOV' # fx, fy, cx, cy, omega
    SIMPLE_RADIAL_FISHEYE = 'SIMPLE_RADIAL_FISHEYE' # f, cx, cy, k
    RADIAL_FISHEYE = 'RADIAL_FISHEYE' # f, cx, cy, k1, k2
    THIN_PRISM_FISHEYE = 'THIN_PRISM_FISHEYE' # fx, fy, cx, cy, k1, k2, p1, p2, k3, k4, sx1, sy1
    UNKNOWN = 'UNKNOWN'

    @staticmethod
    def fromJson(jdata):
        if jdata in ('SIMPLE_PINHOLE', 'simple_pinhole'):
            return CameraModel.SIMPLE_PINHOLE
        elif jdata in ('PINHOLE', 'pinhole'):
            return CameraModel.PINHOLE
        elif jdata in ('SIMPLE_RADIAL', 'simple_radial'):
            return CameraModel.SIMPLE_RADIAL
        elif jdata in ('RADIAL', 'radial'):
            return CameraModel.RADIAL
        elif jdata in ('OPENCV', 'opencv'):
            return CameraModel.OPENCV
        elif jdata in ('OPENCV_FISHEYE', 'opencv_fisheye'):
            return CameraModel.OPENCV_FISHEYE
        elif jdata in ('FULL_OPENCV', 'full_opencv'):
            return CameraModel.FULL_OPENCV
        elif jdata in ('FOV', 'fov'):
            return CameraModel.FOV
        elif jdata in ('SIMPLE_RADIAL_FISHEYE', 'simple_radial_fisheye'):
            return CameraModel.SIMPLE_RADIAL_FISHEYE
        elif jdata in ('RADIAL_FISHEYE', 'radial_fisheye'):
            return CameraModel.RADIAL_FISHEYE
        elif jdata in ('THIN_PRISM_FISHEYE', 'thin_prism_fisheye'):
            return CameraModel.THIN_PRISM_FISHEYE
        elif jdata in ('UNKNOWN', 'unknown'):
            return CameraModel.UNKNOWN
        else:
            raise NotImplementedError

class CameraParameters(object):
    def __init__(self, model = CameraModel.UNKNOWN, modelParams = None, minMaxDepth = None, minMaxDisparity = None):
        self.model = model # [optional] // TODO: string in the v1 standard, but enum is better suited here
        if modelParams is None:
            self.modelParams = []
        else:
            self.modelParams = modelParams # [optional]
        if minMaxDepth is None:
            self.minMaxDepth = []
        else:
            self.minMaxDepth = minMaxDepth # [optional] // for depth image
        if minMaxDisparity is None:
            self.minMaxDisparity = []
        else:
            self.minMaxDisparity = minMaxDisparity # [optional] // for disparity image

    def __str__(self):
        return "{" + \
            "model:" + str(self.model) + "," + \
            "modelParams:" + str(self.modelParams) + "," + \
            "minMaxDepth:" + str(self.minMaxDepth) + "," + \
            "minMaxDisparity:" + str(self.minMaxDisparity) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        cameraParameters = CameraParameters()
        if "model" in jdata:
            cameraParameters.model = CameraModel.fromJson(jdata["model"])
        if "modelParams" in jdata:
            cameraParameters.modelParams = jdata["modelParams"]
        if "minMaxDepth" in jdata:
            cameraParameters.minMaxDepth = jdata["minMaxDepth"]
        if "minMaxDisparity" in jdata:
            cameraParameters.minMaxDisparity = jdata["minMaxDisparity"]
        return cameraParameters

class Privacy(object):
    def __init__(self, dataRetention = None, dataAcceptableUse = None, dataSanitizationApplied = None, dataSanitizationRequested = None):
        if dataRetention is None:
            self.dataRetention = []
        else:
            self.dataRetention = dataRetention # acceptable policies for server-side data retention
        if dataAcceptableUse is None:
            self.dataAcceptableUse = []
        else:
            self.dataAcceptableUse = dataAcceptableUse # acceptable policies for server-side data use
        if dataSanitizationApplied is None:
            self.dataSanitizationApplied = []
        else:
            self.dataSanitizationApplied = dataSanitizationApplied # client-side data sanitization applied
        if dataSanitizationRequested is None:
            self.dataSanitizationRequested = []
        else:
            self.dataSanitizationRequested = dataSanitizationRequested # server-side data sanitization requested

    def __str__(self):
        return "{" + \
            "dataRetention:" + str(self.dataRetention) + "," + \
            "dataAcceptableUse:" + str(self.dataAcceptableUse) + "," + \
            "dataSanitizationApplied:" + str(self.dataSanitizationApplied) + "," + \
            "dataSanitizationRequested:" + str(self.dataSanitizationRequested) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return Privacy(dataRetention=jdata["dataRetention"],
                       dataAcceptableUse=jdata["dataAcceptableUse"],
                       dataSanitizationApplied=jdata["dataSanitizationApplied"],
                       dataSanitizationRequested=jdata["dataSanitizationRequested"])

class CameraReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                sequenceNumber = 0, imageFormat = ImageFormat.UNKNOWN, size = [0,0], imageBytes = [],
                imageOrientation = ImageOrientation(), params = CameraParameters()):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.sequenceNumber = sequenceNumber
        self.imageFormat = imageFormat # TODO: string or enum?
        self.size = size # width, height
        self.imageBytes = imageBytes # base64 encoded image data
        self.imageOrientation = imageOrientation # [optional]
        self.params = params # [optional]

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "sequenceNumber:" + str(self.sequenceNumber) + "," + \
            "imageFormat:" + str(self.imageFormat) + "," + \
            "size:" + str(self.size) + "," + \
            "imageBytes:" + str(self.imageBytes) + "," + \
            "imageOrientation:" + str(self.imageOrientation) + "," + \
            "params:" + str(self.params) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        if "imageOrientation" in jdata:
            imageOrientation = ImageOrientation.fromJson(jdata["imageOrientation"])
        else:
            imageOrientation = ImageOrientation()
        if "params" in jdata:
            params = CameraParameters.fromJson(jdata["params"])
        else:
            params = CameraParameters()
        return CameraReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                             privacy=Privacy.fromJson(jdata["privacy"]),
                             sequenceNumber=jdata["sequenceNumber"],
                             imageFormat=ImageFormat.fromJson(jdata["imageFormat"]),
                             size=jdata["size"], imageBytes=jdata["imageBytes"],
                             imageOrientation=imageOrientation,
                             params=params)

class GeolocationReading(object):
    # aligns with https://w3c.github.io/geolocation-sensor/
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 latitude = 0.0, longitude = 0.0, altitude = 0.0, accuracy = 0.0, altitudeAccuracy = 0.0, heading = 0.0, speed = 0.0):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.latitude = latitude
        self.longitude = longitude
        self.altitude = altitude
        self.accuracy = accuracy
        self.altitudeAccuracy = altitudeAccuracy
        self.heading = heading
        self.speed = speed

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "latitude:" + str(self.latitude) + "," + \
            "longitude:" + str(self.longitude) + "," + \
            "altitude:" + str(self.altitude) + "," + \
            "accuracy:" + str(self.accuracy) + "," + \
            "altitudeAccuracy:" + str(self.altitudeAccuracy) + "," + \
            "heading:" + str(self.heading) + "," + \
            "speed:" + str(self.speed) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return GeolocationReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                                  privacy=Privacy.fromJson(jdata["privacy"]),
                                  latitude=jdata["latitude"], longitude=jdata["longitude"], altitude=jdata["altitude"],
                                  accuracy=jdata["accuracy"], altitudeAccuracy=jdata["altitudeAccuracy"],
                                  heading=jdata["heading"], speed=jdata["speed"])

class WiFiReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 BSSID = "", frequency = 0.0, RSSI = 0.0, SSID = "", scanTimeStart = 0, scanTimeEnd = 0):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.BSSID = BSSID
        self.frequency = frequency # TODO: shouldn't this be a frequency range?
        self.RSSI = RSSI # TODO: shouldn't this be a vector?
        self.SSID = SSID
        self.scanTimeStart = scanTimeStart # The number of milliseconds since the Unix Epoch.
        self.scanTimeEnd = scanTimeEnd # The number of milliseconds since the Unix Epoch.

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "BSSID:" + str(self.BSSID) + "," + \
            "frequency:" + str(self.frequency) + ',' + \
            "RSSI:" + str(self.RSSI) + "," + \
            "SSID:" + str(self.SSID) + ',' + \
            "scanTimeStart:" + str(self.scanTimeStart) + "," + \
            "scanTimeEnd:" + str(self.scanTimeEnd) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return WiFiReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                           privacy=Privacy.fromJson(jdata["privacy"]),
                           BSSID=jdata["BSSID"], frequency=jdata["frequency"], RSSI=jdata["RSSI"],
                           SSID=jdata["SSID"], scanTimeStart=jdata["scanTimeStart"], scanTimeEnd=jdata["scanTimeEnd"])

class BluetoothReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 address = "", RSSI = 0.0, name = ""):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.address = address
        self.RSSI = RSSI # TODO: shouldn't this be a vector?
        self.name = name

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "address:" + str(self.address) + "," + \
            "RSSI:" + str(self.RSSI) + ',' + \
            "name:" + str(self.name) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return BluetoothReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                                privacy=Privacy.fromJson(jdata["privacy"]),
                                address=jdata["address"], RSSI=jdata["RSSI"], name=jdata["name"])

class AccelerometerReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 x = 0.0, y = 0.0, z = 0.0):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "x:" + str(self.x) + "," + \
            "y:" + str(self.y) + ',' + \
            "z:" + str(self.z) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return AccelerometerReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                                    privacy=Privacy.fromJson(jdata["privacy"]),
                                    x=jdata["x"], y=jdata["y"], z=jdata["z"])

class GyroscopeReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 x = 0.0, y = 0.0, z = 0.0):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "x:" + str(self.x) + "," + \
            "y:" + str(self.y) + ',' + \
            "z:" + str(self.z) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return GyroscopeReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                                privacy=Privacy.fromJson(jdata["privacy"]),
                                x=jdata["x"], y=jdata["y"], z=jdata["z"])

class MagnetometerReading(object):
    def __init__(self, timestamp = 0, sensorId = "", privacy = Privacy(),
                 x = 0.0, y = 0.0, z = 0.0):
        self.timestamp = timestamp # The number of milliseconds* since the Unix Epoch.
        self.sensorId = sensorId
        self.privacy = privacy
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        return "{" + \
            "timestamp:" + str(self.timestamp) + "," + \
            "sensorId:" + str(self.sensorId) + "," + \
            "privacy:" + str(self.privacy) + "," + \
            "x:" + str(self.x) + "," + \
            "y:" + str(self.y) + ',' + \
            "z:" + str(self.z) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return MagnetometerReading(timestamp=jdata["timestamp"], sensorId=jdata["sensorId"],
                                   privacy=Privacy.fromJson(jdata["privacy"]),
                                   x=jdata["x"], y=jdata["y"], z=jdata["z"])

class Sensor(object):
    def __init__(self, type:SensorType = SensorType.UNKNOWN, id:str = "", name:str = "", model:str = "",
                 rigIdentifier = "", rigRotation = Quaternion(), rigTranslation = Vector3()):
        self.type = type # camera, geolocation, wifi, bluetooth, accelerometer, gyroscope, magnetometer
        self.id = id
        self.name = name # [optional]
        self.model = model # [optional] // TODO: is this CameraModel or other model? If CameraModel, it is redundant here and should be inside params only.
        self.rigIdentifier = rigIdentifier # [optional]
        self.rigRotation = rigRotation # [optional] // rotation quaternion from rig to sensor
        self.rigTranslation = rigTranslation # [optional] //  translation vector from rig to sensor

    def __str__(self):
        return "{" + \
            "type:" + str(self.type) + "," + \
            "id:" + str(self.id) + "," + \
            "name:" + str(self.name) + "," + \
            "model:" + str(self.model) + "," + \
            "rigIdentifier:" + str(self.rigIdentifier) + ',' + \
            "rigRotation:" + str(self.rigRotation) + ',' + \
            "rigTranslation:" + str(self.rigTranslation) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        sensor = Sensor(type=SensorType.fromJson(jdata["type"]), id=jdata["id"])
        if "name" in jdata:
            sensor.name=jdata["name"],
        if "model" in jdata:
            sensor.model=jdata["model"]
        if "rigIdentifier" in jdata:
            sensor.rigIdentifier=jdata["rigIdentifier"]
        if "rigRotation" in jdata:
            sensor.rigRotation = Quaternion.fromJson(jdata["rigRotation"])
        if "rigTranslation" in jdata:
            sensor.rigTranslation = Vector3.fromJson(jdata["rigTranslation"])
        return sensor

class SensorReadings(object):
    def __init__(self, cameraReadings:[CameraReading] = None, geolocationReadings:[GeolocationReading] = None,
                 accelerometerReadings:[AccelerometerReading] = None, gyroscopeReadings:[GyroscopeReading] = None,
                 magnetometerReadings:[MagnetometerReading] = None, wifiReadings:[WiFiReading] = None,
                 bluetoothReadings:[BluetoothReading] = None):
        if cameraReadings is None:
            self.cameraReadings = []
        else:
            self.cameraReadings = cameraReadings # [optional]
        if geolocationReadings is None:
            self.geolocationReadings = []
        else:
            self.geolocationReadings = geolocationReadings # [optional]
        if accelerometerReadings is None:
            self.accelerometerReadings = []
        else:
            self.accelerometerReadings = accelerometerReadings # [optional]
        if gyroscopeReadings is None:
            self.gyroscopeReadings = []
        else:
            self.gyroscopeReadings = gyroscopeReadings # [optional]
        if magnetometerReadings is None:
            self.magnetometerReadings = []
        else:
            self.magnetometerReadings = magnetometerReadings # [optional]
        if wifiReadings is None:
            self.wifiReadings = []
        else:
            self.wifiReadings = wifiReadings # [optional]
        if bluetoothReadings is None:
            self.bluetoothReadings = []
        else:
            self.bluetoothReadings = bluetoothReadings # [optional]

    def __str__(self):
        return "{" + \
            "cameraReadings:" + str(self.cameraReadings) + "," + \
            "geolocationReadings:" + str(self.geolocationReadings) + "," + \
            "accelerometerReadings:" + str(self.accelerometerReadings) + "," + \
            "gyroscopeReadings:" + str(self.gyroscopeReadings) + "," + \
            "magnetometerReadings:" + str(self.magnetometerReadings) + ',' + \
            "wifiReadings:" + str(self.wifiReadings) + ',' + \
            "bluetoothReadings:" + str(self.bluetoothReadings) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        sensorReadings = SensorReadings()
        if "cameraReadings" in jdata:
            for jcameraReading in jdata["cameraReadings"]:
                sensorReadings.cameraReadings.append(CameraReading.fromJson(jcameraReading))
        if "geolocationReadings" in jdata:
            for jgeolocationReading in jdata["geolocationReadings"]:
                sensorReadings.geolocationReadings.append(GeolocationReading.fromJson(jgeolocationReading))
        if "accelerometerReadings" in jdata:
            for jaccelerometerReading in jdata["accelerometerReadings"]:
                sensorReadings.accelerometerReadings.append(AccelerometerReading.fromJson(jaccelerometerReading))
        if "gyroscopeReadings" in jdata:
            for jgyroscopeReading in jdata["gyroscopeReadings"]:
                sensorReadings.gyroscopeReadings.append(GyroscopeReading.fromJson(jgyroscopeReading))
        if "magnetometerReadings" in jdata:
            for jmagnetormeterReading in jdata["magnetometerReadings"]:
                sensorReadings.magnetometerReadings.append(MagnetometerReading.fromJson(jmagnetormeterReading))
        if "wifiReadings" in jdata:
            for jwifiReading in jdata["wifiReadings"]:
                sensorReadings.wifiReadings.append(WiFiReading.fromJson(jwifiReading))
        if "bluetoothReadings" in jdata:
            for jbluetoothReading in jdata["bluetoothReadings"]:
                sensorReadings.bluetoothReadings.append(BluetoothReading.fromJson(jbluetoothReading))
        return sensorReadings

class GeoPoseAccuracy(object):
    def __init__(self, position = sys.float_info.max, orientation = sys.float_info.max):
        self.position = position # mean for all components in meters
        self.orientation = orientation # mean for all 3 angles in degrees

    def __str__(self):
        return "{" + \
            "position:" + str(self.position) + ',' + \
            "orientation:" + str(self.orientation) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return GeoPoseAccuracy(**jdata)

class GeoPoseResponse(object):
    def __init__(self, type:str = "geopose", id:str = str(uuid.uuid4()), timestamp = datetime.now(timezone.utc).timestamp()*1000,
                accuracy:GeoPoseAccuracy = GeoPoseAccuracy(), geopose:GeoPose = GeoPose()):
        self.type = type # ex. geopose
        self.id = id
        self.timestamp = timestamp # The number of milliseconds since the Unix Epoch.
        self.accuracy = accuracy
        self.geopose = geopose

    def __str__(self):
        return "{" + \
            "type:" + str(self.type) + ',' + \
            "id:" + str(self.id) + ',' + \
            "timestamp:" + str(self.timestamp) + ',' + \
            "accuracy:" + str(self.accuracy) + ',' + \
            "geopose:" + str(self.geopose) + \
        "}"

    def toJson(self):
        return json.dumps(self, default=lambda o: o.__dict__)

    @staticmethod
    def fromJson(jdata):
        accuracy = GeoPoseAccuracy.fromJson(jdata["accuracy"])
        geopose = GeoPose.fromJson(jdata["geopose"])
        return GeoPoseResponse(type=jdata["type"], id=jdata["id"], timestamp=jdata["timestamp"], accuracy=accuracy, geopose=geopose)

class GeoPoseRequest(object):
    def __init__(self, type:str = "geopose", id:str = str(uuid.uuid4()), timestamp = datetime.now(timezone.utc).timestamp()*1000,
                 sensors:[Sensor] = None, sensorReadings:SensorReadings = None, priorPoses:[GeoPoseResponse] = None):
        self.type = type # ex. geopose
        self.id = id
        self.timestamp = timestamp # The number of milliseconds since the Unix Epoch.
        if sensors is None:
            self.sensors = []
        else:
            self.sensors = sensors
        if sensorReadings is None:
            self.sensorReadings = SensorReadings()
        else:
            self.sensorReadings = sensorReadings
        if priorPoses is None:
            self.priorPoses = []
        else:
            self.priorPoses = priorPoses # [optional] # TODO: are these of type GeoPose or GeoPoseResponse?

    def __str__(self):
        return "{" + \
            "type:" + str(self.type) + ',' + \
            "id:" + str(self.id) + ',' + \
            "timestamp:" + str(self.timestamp) + ',' + \
            "sensors:" + str(self.sensors) + ',' + \
            "sensorReadings:" + str(self.sensorReadings) + ',' + \
            "priorPoses:" + str(self.priorPoses) + \
        "}"

    def toJson(self):
        return json.dumps(self, default=lambda o: o.__dict__)

    @staticmethod
    def fromJson(jdata):
        sensors = []
        for jsensor in jdata["sensors"]:
            sensors.append(Sensor.fromJson(jsensor))
        sensorReadings = SensorReadings.fromJson(jdata["sensorReadings"])
        priorPoses = []
        if "priorPoses" in jdata:
            for jpriorPose in jdata["priorPoses"]:
                priorPoses.append(GeoPoseResponse.fromJson(jpriorPose))
        else:
            priorPoses = []
        return GeoPoseRequest(type=jdata["type"], id=jdata["id"], timestamp=jdata["timestamp"],
                              sensors=sensors, sensorReadings=sensorReadings, priorPoses=priorPoses)

def parse_accept_type(accept_header:str):
    TYPE_REGEX = re.compile(
        r'application/vnd\.oscp\+json'# OSCP JSON
    )
    type = TYPE_REGEX.search(accept_header)
    if type == None:
        return False
    return True

def parse_accept_version(accept_header:str):
    VERSION_REGEX = re.compile(
        r'version='                 # version=
        r'(?P<major>[0-9]+)'        # capture major number
        r'(?:.(?P<minor>[0-9]+))?'  # capture minor number if exists
    )
    version = VERSION_REGEX.search(accept_header)
    if version == None:
        return False, None, None

    majorStr = version.groupdict()['major']
    minorStr = version.groupdict()['minor']
    try:
        major = int(majorStr)
        minor = None if minorStr == None else int(minorStr)
    except:
        return False, None, None
    return True, major, minor

def verify_version_header(headers):
    if headers.get('Accept') is None:
        return False, None, None

    if not parse_accept_type(headers.get('Accept')):
        return False, None, None

    return parse_accept_version(headers.get('Accept'))
