# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


import time

from base_localizer import BaseLocalizer, LocalizationResult
from oscp.geopose import GeoPose, Position
from oscp.geoposeprotocol import CameraParameters

# default coordinates at Nokia Budapest
kDefaultLat = 47.48591791954986
kDefaultLon = 19.079377689751166


class DummyLocalizer(BaseLocalizer):

    def localize(self, query_image, camera_parameters: CameraParameters) -> LocalizationResult:
        time.sleep(1)
        dummy_geo_pose = GeoPose(position=Position(lat=kDefaultLat, lon=kDefaultLon))
        return LocalizationResult(geoposes=[dummy_geo_pose], framed_poses=[])
