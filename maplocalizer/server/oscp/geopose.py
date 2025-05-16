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

class Position(object):
    def __init__(self, lat = 0.0, lon = 0.0, h = 0.0):
        self.lat = lat
        self.lon = lon
        self.h = h

    def __str__(self):
        return "{" + \
            "lat:" + str(self.lat) + "," + \
            "lon:" + str(self.lon) + ',' + \
            "h:" + str(self.h) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return Position(**jdata)

class Vector3(object):
    def __init__(self, x = 0.0, y = 0.0, z = 0.0):
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        return "{" + \
            "x:" + str(self.x) + "," + \
            "y:" + str(self.y) + ',' + \
            "z:" + str(self.z) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return Vector3(**jdata)

class Quaternion(object):
    def __init__(self, x = 0.0, y = 0.0, z = 0.0, w = 1.0):
        self.x = x
        self.y = y
        self.z = z
        self.w = w

    def __str__(self):
        return "{" + \
            "x:" + str(self.x) + "," + \
            "y:" + str(self.y) + ',' + \
            "z:" + str(self.z) + ',' + \
            "w:" + str(self.w) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return Quaternion(**jdata)

class GeoPose(object):
    def __init__(self, position = Position(), quaternion = Quaternion()):
        self.position = position
        self.quaternion = quaternion

    def __str__(self):
        return "{" + \
            "position:" + str(self.position) + "," + \
            "quaternion:" + str(self.quaternion) + \
        "}"

    @staticmethod
    def fromJson(jdata):
        return GeoPose(position=Position.fromJson(jdata["position"]), quaternion=Quaternion.fromJson(jdata["quaternion"]))
