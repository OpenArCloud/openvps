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
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set, Tuple

from oscp.geoposeprotocol import GeoPoseRequest, verify_version_header
from oscp.geoposeprotocol_ext import GeoPoseResponseExtended
from oscp.spatialdds_types import FramedPose, Time
import base64

# Note: large numpy and cv2 are only used for decoding the image, but this could be solved with simpler libs too
import numpy as np
import cv2

from hloc_localizer import HlocLocalizer

from test_gpu import getGpuInfo

import env
from functools import lru_cache

# Vendored SpatialDDS packages live beside this file rather than on the system path, so the
# image needs no install step for them and the copy is visibly pinned. See vendor/README.md.
import os as _os
import sys as _sys
_VENDOR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "vendor")
if _VENDOR not in _sys.path:
    _sys.path.insert(0, _VENDOR)


@lru_cache
def get_settings():
    return env.Settings()


# --- SpatialDDS -----------------------------------------------------------------------
# Entirely additive and off unless OPENVPS_DDS_ENABLED is set, so a deployment that does not
# want a DDS participant behaves exactly as it did before. The HTTP path below is unchanged
# either way: both surfaces call the same localizer through the same single worker, because
# the GPU serialises regardless and letting two threads into HlocLocalizer would race its
# per-call state.
_dds_runtime = None
_dds_worker = None
_dds_heartbeat = None
_dds_announcer = None


def _dds_announce_current() -> None:
    """
    Re-advertise whichever map the DDS path now serves.

    Called after every load and unload, because the announce has to follow currentMapId:
    VpsRequest has no map field, so the DDS path answers from currentMapId, and announcing
    any other map would advertise one this service will not localize against. A map with no
    geodetic anchor is not announced at all — see ServiceAnnouncer.set_map.
    """
    if _dds_announcer is None:
        return
    try:
        if currentMapId is None or currentMapId not in localizers:
            _dds_announcer.clear()
        else:
            _dds_announcer.set_map(currentMapId, localizers[currentMapId])
    except Exception:
        # Discovery is not worth failing a map load over: the map is still servable to a
        # client that names it, and the next load retries.
        traceback.print_exc()


def _pinhole_params(cam):
    """
    (fx, fy, cx, cy) from a COLMAP camera, whatever model it uses.

    COLMAP packs parameters differently per model and the leading four are not intrinsics in
    a fixed order. The single-focal models carry (f, cx, cy, ...) and need f duplicated;
    only the two-focal models are already (fx, fy, cx, cy). Distortion is dropped, which is
    what the HTTP path does too — the localizer is asked for a PINHOLE camera either way.
    """
    p = [float(x) for x in cam.params]
    name = cam.model.name if hasattr(cam.model, "name") else str(cam.model)
    if name in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "SIMPLE_RADIAL_FISHEYE", "RADIAL",
                "RADIAL_FISHEYE"):
        return [p[0], p[0], p[1], p[2]]
    if len(p) >= 4:
        return [p[0], p[1], p[2], p[3]]
    raise ValueError(f"cannot derive pinhole intrinsics from camera model {name} with {p}")


def _dds_localize(image_bytes, request):
    """Adapt a VpsRequest to the localizer. Runs on the shared worker, never on the loop."""
    import cv2 as _cv2
    import numpy as _np
    from spatialdds.service import LocalizeOutcome

    buf = _np.frombuffer(image_bytes, dtype=_np.uint8)
    img = _cv2.imdecode(buf, _cv2.IMREAD_COLOR_BGR)
    if img is None:
        return None

    global currentMapId
    if currentMapId is None or currentMapId not in localizers:
        return None
    localizer = localizers[currentMapId]
    _touch_map(currentMapId)

    # VpsRequest carries no camera intrinsics of its own, and query_stream_id would point at
    # a VisionMeta this service does not publish, so the map's own camera model is used.
    # That is correct for query images drawn from the map and wrong for a foreign camera —
    # the gap is that the 1.7 request has nowhere to put intrinsics.
    #
    # The COLMAP model must be translated, not truncated. An earlier version took the first
    # four params and called them PINHOLE; on a SIMPLE_RADIAL map, whose params are
    # (f, cx, cy, k), that fed cx in as fy and cy in as cx. The result localized, returned
    # VPS_SUCCESS with enough inliers to pass the threshold, and was 9.6 m out — plausible,
    # wrong, and silent, which is the failure mode this whole binding is meant to avoid.
    from oscp.geoposeprotocol import CameraParameters
    cam = localizer.reconstruction.cameras[
        next(iter(localizer.reconstruction.images.values())).camera_id]
    params = CameraParameters()
    params.model = "PINHOLE"
    params.modelParams = _pinhole_params(cam)

    result = localizer.localize(img, params)
    if result is None or not result.framed_poses:
        return None
    if _dds_heartbeat is not None:
        _dds_heartbeat.beat()
    return LocalizeOutcome(
        framed_poses=list(result.framed_poses),
        geoposes=list(result.geoposes),
        # Upstream does not surface the inlier ratio yet, so this is a placeholder rather
        # than a measurement. Publishing a fabricated confidence would be worse than saying
        # so here: see docs note on deriving it from inliers / PnP correspondences.
        confidence=1.0 if result.geoposes or result.framed_poses else 0.0,
        map_id=currentMapId,
        georeferenced=bool(result.geoposes),
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _dds_runtime, _dds_worker, _dds_heartbeat, _dds_announcer
    from spatialdds import runtime as _rt
    if _rt.enabled():
        try:
            from cyclonedds.domain import DomainParticipant
            from spatialdds.service import VpsService
            _dds_worker = _rt.SharedWorker()
            _dds_heartbeat = _rt.Heartbeat()
            participant = DomainParticipant(_rt.domain_id())
            service = VpsService(
                participant,
                _os.environ.get("OPENVPS_SERVICE_ID", "svc:vps:openvps/local;v=dev"),
                lambda img, req: _dds_worker.run(_dds_localize, img, req),
                # Lets the service honour a ;v=<map_id> in the request: the announce
                # advertises that form, so a discovering client will send it back.
                current_revision=lambda: currentMapId,
            )
            from spatialdds.announce import ServiceAnnouncer
            _dds_announcer = ServiceAnnouncer(
                participant,
                _os.environ.get("OPENVPS_SERVICE_ID", "svc:vps:openvps/local"),
                _os.environ.get("OPENVPS_ORG", "openvps"),
            )
            _dds_runtime = _rt.DdsRuntime(service, announcer=_dds_announcer)
            _dds_runtime.start()
            # A map may already be loaded if this is a restart with a warm pool.
            _dds_announce_current()
        except Exception:
            # A DDS failure must not stop the HTTP service coming up. The localizer is
            # useful without it, and a half-started process that serves neither is worse.
            traceback.print_exc()
            print("SpatialDDS participant failed to start; HTTP path unaffected")
    yield
    if _dds_runtime is not None:
        _dds_runtime.stop()
    if _dds_worker is not None:
        _dds_worker.shutdown()


app = FastAPI(lifespan=_lifespan)

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
currentMapId: Optional[str] = None

access_times: Dict[str, float] = {}

# print the env file
print(get_settings())

# print the GPU details
print("Checking GPU availability...")
print(getGpuInfo())


def _touch_map(map_id: str) -> None:
    access_times[map_id] = time.perf_counter()


def _loaded_map_count() -> int:
    return len(localizers)


def _unload_map(map_id: str) -> None:
    global currentMapId
    localizer = localizers.pop(map_id, None)
    if localizer is not None and hasattr(localizer, "close"):
        localizer.close()
    mapConfigs.pop(map_id, None)
    access_times.pop(map_id, None)
    if currentMapId == map_id:
        currentMapId = None
        # Announce from here rather than from /unload_map, because LRU eviction comes
        # through this function too. Hooked at the endpoint only, an evicted map would go
        # on being advertised after the service had stopped serving it — and with
        # maxLoadedMaps now 1, eviction is the common path rather than the rare one.
        _dds_announce_current()


def _evict_one_lru(exempt: Set[str]) -> None:
    candidates = [k for k in localizers if k not in exempt]
    if not candidates:
        return
    victim = min(candidates, key=lambda k: access_times.get(k, 0.0))
    _unload_map(victim)
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
        _dds_announce_current()
        return True, ""

    limit = settings.maxLoadedMaps
    if limit > 0:
        while _loaded_map_count() >= limit and map_id not in localizers:
            before = _loaded_map_count()
            _evict_one_lru({map_id})
            if _loaded_map_count() == before:
                break

    localizer: Optional[HlocLocalizer] = None
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
            localizer.close()
            _unload_map(map_id)
            return False, f"Failed to load map transform {map_id}: {ex}"

        localizer.load_map(map_config, map_id=map_id)
        localizers[map_id] = localizer
        currentMapId = map_id
        _touch_map(map_id)
        _dds_announce_current()
        return True, ""
    except Exception as ex:
        if localizer is not None:
            localizer.close()
        _unload_map(map_id)
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
    loaded = list(localizers.keys())
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
    # A transform reload can make a map announceable that was not before: the geodetic
    # anchor is what gates discovery, and this is the endpoint that supplies it. Without
    # this, georeferencing a live map left it undiscoverable until someone reloaded it.
    _dds_announce_current()
    return {"STATUS": f"Successfully updated the transform of map {id}"}


# TODO: change to POST. We have it as GET for now so that it can be triggered simply from a browser
@app.get("/unload_map/{id}")
async def unload_map(id: str):
    _unload_map(id)
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
            if currentMapId is None:
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
