# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)


from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

import time
from oscp.geoposeprotocol import GeoPoseRequest, GeoPoseResponse, verify_version_header
import base64

# Note: large numpy and cv2 are only used for decoding the image, but this could be solved with simpler libs too
import numpy as np
import cv2

from hloc_localizer import HlocLocalizer
from dummy_localizer import DummyLocalizer

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

allMapIdsAndPaths = {}
mapConfigs = {}
localizers = {}

# NOTE(soeroesg): for educational purposes, we have here a DummyLocalizer
# which always returns the same GeoPose but can be used for testing the GeoPoseProtocol
currentMapId = "dummy"
mapConfigs["dummy"] = {}
localizers["dummy"] = DummyLocalizer()

# print the env file
print(get_settings())


@app.get("/")
def read_root():
    return {"STATUS":"OpenVPS MapLocalizer is running. Use the /localize/geopose endpoint"}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get('/load_map/{id}')
async def load_map(id:str, response: Response):
    print("Loading map: " + str(id))
    # NOTE: in the future, we can check whether this ID belongs to an HLoc map or other type of map, and load accordingly

    # check whether map with this id exists
    settings = get_settings()
    uploadsDir = settings.uploadsDir
    mapsRootDir = uploadsDir # currently the maps are in the same folder as the uploads
    mapsRootDirDocker = '/uploads' # NOTE: this must be the same as in the Dockerfile.
    # We use it below to rewrite existing paths, so that maps created in a dockerized MapBuilder
    # can be also used in a locally running MapLocalizer

    global allMapIdsAndPaths
    allMapIdsAndPaths = HlocLocalizer.get_all_map_ids_and_paths(mapsRootDir)
    if not id in allMapIdsAndPaths.keys():
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"ERROR":f"There is no map with id {id}"}

    global currentMapId
    # check whether already loaded
    if id in mapConfigs.keys() and id in localizers.keys():
        currentMapId = id # it was already loaded, now make it current
        return {"STATUS":f"Already loaded map {id}"}

    try:
        mapPath = allMapIdsAndPaths[id]
        configPath = mapPath / 'config.yaml'
        transformPath = mapPath / 'transform.json'
        mapConfig = HlocLocalizer.load_map_config(configPath, mapsRootDirDocker, mapsRootDir)
        if mapConfig is None:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {"ERROR":f"Failed to load map config {id}"}
        mapConfigs[id] = mapConfig

        localizer = HlocLocalizer(debug=get_settings().debug)
        if not localizer.load_map_transform(transformPath):
            del mapConfigs[id]
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return {"ERROR":f"Failed to load map transform {id}"}

        localizer.load_map(mapConfig)
        localizers[id] = localizer
        currentMapId = id
        return {"STATUS":f"Successfully loaded map {id}"}
    except:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR":f"Failed to load map {id}"}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get('/load_transform/{id}')
async def load_transform(id:str, response: Response):
    if not id in allMapIdsAndPaths.keys():
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR":f"There is no map with id {id}. Try to load it first."}
    if not id in localizers.keys():
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR":f"There is no map loaded with id {id}. Try to load it first."}
    mapPath = allMapIdsAndPaths[id]
    transformPath = mapPath / 'transform.json'
    if not localizers[id].load_map_transform(transformPath):
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR":f"Failed to load map transform {id}"}
    return {"STATUS":f"Successfully updated the transform of map {id}"}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get('/unload_map/{id}')
async def unload_map(id:str):
    # check whether already loaded
    if id in mapConfigs:
        del mapConfigs[id]
    if id in localizers:
        del localizers[id]
    return {"STATUS":f"Unloaded map {id}"}


@app.get('/localize/geopose')
async def localize():
    return {"STATUS":"GeoPose server is running"}


@app.get("/root_path")
def read_main(request: Request):
    return {"root_path": request.scope.get("root_path")}


@app.get("/current_map_id")
def read_main():
    return {"id": currentMapId}


@app.post('/localize/geopose')
async def localize(request: Request, response: Response):
    try:

        # First verify the protocol version from the Accept header
        success, versionMajor, versionMinor = verify_version_header(request.headers)
        if not success:
            errorMessage = "The request has no or malformed Accept header. Add the header application/vnd.oscp+json;version=2.0"
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR" : errorMessage}
        if get_settings().debug:
            print(f"Version: {versionMajor} {versionMinor}")
        if versionMajor != 2 or versionMinor != 0:
            errorMessage = "This server supports only GPP v2.0"
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR" : errorMessage}

        jRequest = await request.json()

        gppRequest = GeoPoseRequest.fromJson(jRequest)

        # Get and decode the image
        if len(gppRequest.sensorReadings.cameraReadings) < 1:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR":"Request has no camera readings"}

        if gppRequest.sensorReadings.cameraReadings[0].imageBytes is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR":"Request has no image"}

        queryImageData = base64.b64decode(gppRequest.sensorReadings.cameraReadings[0].imageBytes)

        queryImageBuffer = np.frombuffer(queryImageData, dtype=np.uint8)
        queryImage = cv2.imdecode(queryImageBuffer, cv2.IMREAD_COLOR_BGR)
        if queryImage is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR":"Could not decode image"}

        # Get and decode the camera parameters
        if gppRequest.sensorReadings.cameraReadings[0].params is None:
            response.status_code = status.HTTP_400_BAD_REQUEST
            return {"ERROR":"Request has no camera parameters"}

        cameraParameters = gppRequest.sensorReadings.cameraReadings[0].params
        # NOTE: if the image gets resized, we need to resize the camera parameters too

        if get_settings().debug:
            print(cameraParameters)
            gppRequest.sensorReadings.cameraReadings[0].imageBytes = "DELETED" # Delete the image content before logging
            print()
            print(gppRequest.toJson())

        global currentMapId
        if not currentMapId in localizers:
            raise RuntimeError(f"Could not find localizer with id {currentMapId}")
        localizer = localizers[currentMapId]

        t_start = time.perf_counter()
        estimatedGeoPose = localizer.localize(queryImage, cameraParameters)
        t_end = time.perf_counter()
        if get_settings().debug:
            print(f"Elapsed time: {t_end - t_start} ms")
        if estimatedGeoPose is None:
            response.status_code = status.HTTP_501_NOT_IMPLEMENTED
            print(f"Could not localize request {gppRequest.id}")
            return {"ERROR":f"Could not localize request {gppRequest.id}"}

        gppResponse = GeoPoseResponse()
        gppResponse.id = gppRequest.id
        gppResponse.timestamp = gppRequest.timestamp
        gppResponse.geopose = estimatedGeoPose

        if get_settings().debug:
            jResponse = gppResponse.toJson()
            print()
            print(jResponse)
            print()

        response.status_code = status.HTTP_200_OK
        return gppResponse

    except:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"ERROR":"Internal server error"}
