# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from oscp.geopose import GeoPose
from oscp.geoposeprotocol import CameraParameters
from oscp.spatialdds_types import FramedPose


@dataclass
class LocalizationResult:
    """Output of map visual localization: global GeoPose hypotheses and metric poses in map frames."""
    geoposes: List[GeoPose]
    framed_poses: List[FramedPose]


class BaseLocalizer(ABC):
    """Shared contract for map localizers used by MapLocalizer HTTP handlers."""

    @abstractmethod
    def localize(self, query_image, camera_parameters: CameraParameters) -> LocalizationResult:
        """Return poses for the query image; use empty lists when localization fails or is unavailable."""
        raise NotImplementedError
