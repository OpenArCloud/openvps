# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

import time
import datetime
import traceback
from typing import Dict, Optional, Set, Tuple

from oscp.geoposeprotocol import GeoPoseRequest, verify_version_header
from oscp.geoposeprotocol_ext import GeoPoseResponseExtended
from oscp.spatialdds_types import FramedPose, Time
import base64

# Note: large numpy and cv2 are only used for decoding the image, but this could be solved with simpler libs too
import numpy as np
import cv2

from hloc_localizer import HlocLocalizer
from dummy_localizer import DummyLocalizer

from test_gpu import getGpuInfo

import env
from functools import lru_cache


@lru_cache
def get_settings():
    return env.Settings()


app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

allMapIdsAndPaths: Dict[str, object] = {}
mapConfigs: Dict[str, object] = {}
localizers: Dict[str, object] = {}

# NOTE(soeroesg): for educational purposes, we have here a DummyLocalizer
# which always returns the same GeoPose but can be used for testing the GeoPoseProtocol
kDummyMapId = "dummy"
mapConfigs[kDummyMapId] = {}
localizers[kDummyMapId] = DummyLocalizer()
currentMapId = kDummyMapId

access_times: Dict[str, float] = {}

# print the env file
print(get_settings())

# print the GPU details
print("Checking GPU availability...")
print(getGpuInfo())


def _touch_map(map_id: str) -> None:
    if map_id != kDummyMapId:
        access_times[map_id] = time.perf_counter()


def _real_map_count() -> int:
    return len([k for k in localizers if k != kDummyMapId])


def _evict_one_lru(exempt: Set[str]) -> None:
    candidates = [k for k in localizers if k != kDummyMapId and k not in exempt]
    if not candidates:
        return
    victim = min(candidates, key=lambda k: access_times.get(k, 0.0))
    if victim in mapConfigs:
        del mapConfigs[victim]
    if victim in localizers:
        del localizers[victim]
    access_times.pop(victim, None)
    print(f"# LRU evicted map {victim}")


def refresh_maps_index() -> None:
    global allMapIdsAndPaths
    settings = get_settings()
    maps_root = settings.uploadsDir
    allMapIdsAndPaths = HlocLocalizer.get_all_map_ids_and_paths(maps_root)


def load_map_core(map_id: str) -> Tuple[bool, str]:
    """Load HLOC map into memory. Returns (success, error_message)."""
    global currentMapId
    settings = get_settings()
    maps_root = settings.uploadsDir
    maps_root_docker = "/uploads"

    refresh_maps_index()
    if map_id not in allMapIdsAndPaths:
        return False, f"There is no map with id {map_id}"

    if map_id in mapConfigs and map_id in localizers:
        currentMapId = map_id
        _touch_map(map_id)
        return True, ""

    limit = settings.maxLoadedMaps
    if limit > 0:
        while _real_map_count() >= limit and map_id not in localizers:
            before = _real_map_count()
            _evict_one_lru({map_id})
            if _real_map_count() == before:
                break

    try:
        map_path = allMapIdsAndPaths[map_id]
        config_path = map_path / "config.yaml"
        transform_path = map_path / "transform.json"
        map_config = HlocLocalizer.load_map_config(config_path, maps_root_docker, maps_root)
        if map_config is None:
            return False, f"Failed to load map config {map_id}"
        mapConfigs[map_id] = map_config

        localizer = HlocLocalizer(debug=settings.debug)
        try:
            localizer.load_map_transform(transform_path, map_id)
        except Exception as ex:
            del mapConfigs[map_id]
            return False, f"Failed to load map transform {map_id}: {ex}"

        localizer.load_map(map_config, map_id=map_id)
        localizers[map_id] = localizer
        currentMapId = map_id
        _touch_map(map_id)
        return True, ""
    except Exception as ex:
        if map_id in mapConfigs:
            del mapConfigs[map_id]
        if map_id in localizers:
            del localizers[map_id]
        return False, f"Failed to load map {map_id}: {ex}"


def resolve_localize_map_id(request: Request) -> Optional[str]:
    """Prefer ``X-OpenVPS-Map-Id`` from gateway/orchestrator when present."""
    h = request.headers
    v = h.get("x-openvps-map-id") or h.get("X-OpenVPS-Map-Id")
    return v.strip() if v else None


@app.get("/")
def read_root():
    return {"STATUS": "OpenVPS MapLocalizer is running. Use the /localize/geopose endpoint"}


@app.get("/gpu_info")
def gpu_info():
    return getGpuInfo()


@app.get("/health")
def health():
    s = get_settings()
    loaded = [k for k in localizers.keys() if k != kDummyMapId]
    return {"status": "ok", "workerId": s.workerId, "loaded_map_ids": loaded, "current_map_id": currentMapId}


@app.get("/ready")
def ready():
    return {"ready": True}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get("/load_map/{id}")
async def load_map(id: str, response: Response):
    print(f"# {datetime.datetime.now()} Loading map: {str(id)}")
    ok, err = load_map_core(id)
    if ok:
        return {"STATUS": f"Successfully loaded map {id}"}
    response.status_code = status.HTTP_400_BAD_REQUEST if "no map with id" in err else status.HTTP_500_INTERNAL_SERVER_ERROR
    return {"ERROR": err}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get("/load_transform/{id}")
async def load_transform(id: str, response: Response):
    refresh_maps_index()
    if id not in allMapIdsAndPaths:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR": f"There is no map with id {id}. Try to load it first."}
    if id not in localizers:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR": f"There is no map loaded with id {id}. Try to load it first."}
    map_path = allMapIdsAndPaths[id]
    transform_path = map_path / "transform.json"
    try:
        localizers[id].load_map_transform(transform_path, id)
    except Exception as ex:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR": f"Failed to load map transform {id}: {ex}"}
    _touch_map(id)
    return {"STATUS": f"Successfully updated the transform of map {id}"}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get("/unload_map/{id}")
async def unload_map(id: str):
    if id in mapConfigs:
        del mapConfigs[id]
    if id in localizers:
        del localizers[id]
    access_times.pop(id, None)
    return {"STATUS": f"Unloaded map {id}"}


@app.get("/localize/geopose")
async def localize_ping():
    return {"STATUS": "GeoPose server is running"}


@app.get("/root_path")
def root_path(request: Request):
    return {"root_path": request.scope.get("root_path")}


@app.get("/current_map_id")
def current_map_id():
    return {"id": currentMapId}


@app.post("/localize/geopose")
async def localize(request: Request, response: Response):
    try:
        print(f"# {datetime.datetime.now()} localize")
        success, versionMajor, versionMinor = verify_version_header(request.headers)
        if not success:
            errorMessage = "The request has no or malformed Accept header. Add the header application/vnd.oscp+json;version=2.0"
            print(errorMessage)
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR": errorMessage}
        if get_settings().debug:
            print(f"Version: {versionMajor} {versionMinor}")
        if versionMajor != 2 or versionMinor != 0:
            errorMessage = "This server supports only GPP v2.0"
            print(errorMessage)
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR": errorMessage}

        jRequest = await request.json()

        gppRequest = GeoPoseRequest.fromJson(jRequest)

        if len(gppRequest.sensorReadings.cameraReadings) < 1:
            errorMessage = "Request has no camera readings"
            print(errorMessage)
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR": errorMessage}

        if gppRequest.sensorReadings.cameraReadings[0].imageBytes is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            errorMessage = "Request has no image"
            print(errorMessage)
            return {"ERROR": errorMessage}

        queryImageData = base64.b64decode(gppRequest.sensorReadings.cameraReadings[0].imageBytes)

        queryImageBuffer = np.frombuffer(queryImageData, dtype=np.uint8)
        queryImage = cv2.imdecode(queryImageBuffer, cv2.IMREAD_COLOR_BGR)
        if queryImage is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            errorMessage = "Could not decode image"
            print(errorMessage)
            return {"ERROR": errorMessage}

        if gppRequest.sensorReadings.cameraReadings[0].params is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            errorMessage = "Request has no camera parameters"
            print(errorMessage)
            return {"ERROR": errorMessage}

        cameraParameters = gppRequest.sensorReadings.cameraReadings[0].params

        if get_settings().debug:
            print(cameraParameters)
            gppRequest.sensorReadings.cameraReadings[0].imageBytes = "DELETED"
            print()
            print(gppRequest.toJson())

        override_id = resolve_localize_map_id(request)
        global currentMapId
        if override_id:
            ok, err = load_map_core(override_id)
            if not ok:
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                return {"ERROR": err}
            active_id = override_id
        else:
            if currentMapId == kDummyMapId:
                errorMessage = "No map is loaded. Load a map with /load_map/{id} first."
                print(errorMessage)
                response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                return {"ERROR": errorMessage}
            active_id = currentMapId

        if active_id not in localizers:
            raise RuntimeError(f"Could not find localizer with id {active_id}")
        localizer = localizers[active_id]

        t_start = time.perf_counter()
        localizationResult = localizer.localize(queryImage, cameraParameters)
        _touch_map(active_id)

        if get_settings().debug:
            print(f"Localization result: {localizationResult}")

        t_end = time.perf_counter()
        if get_settings().debug:
            print(f"Elapsed time: {t_end - t_start} ms")
        if len(localizationResult.geoposes) == 0 and len(localizationResult.framed_poses) == 0:
            errorMessage = f"Could not localize request {gppRequest.id}"
            print(errorMessage)
            response.status_code = status.HTTP_404_NOT_FOUND
            return {"ERROR": errorMessage}

        ts = int(round(float(gppRequest.timestamp)))
        stamp = Time.from_unix_millis(ts)
        poses_stamped = [
            FramedPose(pose=fp.pose, frame_ref=fp.frame_ref, cov=fp.cov, stamp=stamp)
            for fp in localizationResult.framed_poses
        ]
        poses_list_optional = poses_stamped if len(poses_stamped) > 0 else []
        geoposes_list_optional = localizationResult.geoposes if len(localizationResult.geoposes) > 0 else []
        primary_geopose = localizationResult.geoposes[0] if len(localizationResult.geoposes) > 0 else None
        gppResponseExtended = GeoPoseResponseExtended(
            id=gppRequest.id,
            timestamp=ts,
            geopose=primary_geopose,
            geoposes=geoposes_list_optional,
            poses=poses_list_optional,
        )

        if get_settings().debug:
            jResponse = gppResponseExtended.toJson()
            print()
            print(jResponse)
            print()

        response.status_code = status.HTTP_200_OK
        return gppResponseExtended.to_json_dict()

    except Exception as e:
        if get_settings().debug:
            print(traceback.format_exc())
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR": "Internal server error: " + str(e)}
