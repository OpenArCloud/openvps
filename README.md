# OpenVPS

Open Visual Positioning Service - Main repository with build scripts and documentation. The project was funded by [NGI Search](https://www.ngisearch.eu/view/Events/OC5Searchers) EU Project and [Open AR Cloud](https://www.openarcloud.org/), 2025.

Authors: Andor Kovacs (@KovacsA22), Denes Bisztray (@bisztray), Gabor Soros (@soeroesg)

Copyright 2025 Nokia
Licensed under the MIT License.
SPDX-License-Identifier: MIT


## Modules
The system consists of MapBuilder, MapAligner, MapLocalizer, optional MapRegistry and MapSelector services for indexing and choosing among multiple maps, the [HLOC](https://github.com/cvg/Hierarchical-Localization) third-party mapping and localization framework, and authentication via [FusionAuth](https://fusionauth.io/) to protect the maps.

First, images are captured by a smartphone app (currently the format of [StrayScanner](https://docs.strayrobots.io/) is supported), and uploaded to the **MapBuilder** for processing. The MapBuilder runs the HLOC mapping pipeline, and the map points are also exported as a PLY point cloud. The **MapAligner** loads the PLY point cloud and an OpenStreetMap map tile, and the user manually aligns the point cloud with the building footprints on the map. The resulting 3D transform can be saved to the MapBuilder. Finally, a map with its transform can be loaded into the **MapLocalizer**, which can then localize query images sent by mobile devices. The localization happens in the HLOC map first, but using the geo-alignment transform, the result is converted to OGC GeoPose format. When several maps are deployed, **MapSelector** exposes the same GeoPose endpoint shape but picks the best map from coarse GNSS using **MapRegistry**, then proxies the request to MapLocalizer with the chosen map id.

![System overview](./docs/overview_with_mapselector.jpg)


### Hierarchical-Localization

[HLOC](https://github.com/cvg/Hierarchical-Localization) is a widely used library for visual localization. It contains a wide range of important algorithms. We wrap this library into a map creation service and into a localization service.

### Map Builder

Frontend and backend server code for creating HLOC maps from StrayScanner (and in the future other) RGBD recordings.

Also see [README](mapbuilder/README.md)

![screenshot of MapBuilder](./docs/mapbuilder.jpg)

### Map Aligner

This is a web service that takes a point cloud and an OpenStreetMap tile and allows the user to scale/rotate/translate the point cloud on the map for geo-alignment.

Also see [README](mapaligner/README.md)

![screenshot of MapAligner](./docs/mapaligner.jpg)

### Map Localizer

This is a web service that takes an HLOC map and localizes a query image in it. The response is OGC [GeoPose](https://www.ogc.org/standards/geopose/) format. The API corresponds to the Open AR Cloud [GeoPoseProtocol](https://github.com/OpenArCloud/oscp-geopose-protocol).

Also see [README](maplocalizer/README.md)

### Map Registry

MapRegistry is a small FastAPI service that scans the shared maps tree (the same volume the MapBuilder writes to), enumerates HLOC map folders in the local **map catalog**, and builds a JSON **coverage index** by **ingesting** per-map **`coverage.json`** files (written by MapBuilder). On startup, it runs a full rescan. **`GET /maps`** and **`GET /maps/query`** use **global `map_id`** (UUID folder under `hlocMaps/`); **`dataset_id`** is uploads metadata only (MapBuilder route param and `POST /internal/reload` validation). Duplicate `map_id` values under two datasets are reported on rescan. **`GET /maps/query`** ranks geo-aligned maps by GNSS against **`geo_aabb`** and optional **`geo_footprint`** (`standard` coverage only, maps above latitudes 85 and maps crossing the antimeridian are not supported). **`POST /internal/reload`** and **`POST /internal/rescan`** reload artifacts from disk. The index is `/uploads/map_registry.json`. Host port **`MAPREGISTRY_PORT`** (default **8044**) is published for local development and debugging. See `mapregistry/README.md`.

### Map Selector

MapSelector is the **entry point** for AR clients: same `POST /localize/geopose` as MapLocalizer in former versions of OpenVPS. Map choice uses **prior GeoPose** (`priorPoses[0]`) first, else coarse **GNSS**, then MapRegistry **`GET /maps/query`**, then MapLocalizer with **`X-OpenVPS-Map-Id`**. With no location hint it uses the currently loaded map (no header). With a hint but no nearby indexed map, localization fails with **`ERROR`**. Bounded multi-map retry (off by default) is configured in `mapselector/server/main.py` (`kEnableMultiMapLocalization`, `kMultiMapMaxNumCandidates`; see `mapselector/README.md`). Public GeoPose URL: **`MAPSELECTOR_URL`** (default host port **8046**).

### Authentication
We use FusionAuth for OAuth2 authentication to protect the maps. We chose it because it can run locally on the host machine. Download and run FusionAuth locally in Docker. See [this](/docs/FusionAuth.md) documentation on how to configure FusionAuth.


## Setup

The mapbuilder and maplocalizer require an nvidia GPU, at least in the ballpark of GeForce 1080 but a more powerful one is recommended.

You will also need an own domain name and a corresponding SSL certificate, and you need to forward 4 ports to your host machine. It is recommended to run NGINX on your host machine to terminate the TLS tunnels and forward the connections to the openvps containers that run HTTP servers.


Install `docker` and `nvidia-container-toolkit` ([link](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)) so that the containers can have GPU access.


Continue with the installation and configuration of the authentication, see the description in [this](/docs/FusionAuth.md) document. You will need to create a tenant and an application. Mark the  client ID and client secret of your new application, these will be filled later into our environment variables `AUTH_FUSIONAUTH_ID` and `AUTH_FUSIONAUTH_SECRET`. The `AUTH_SECRET` is a secret generated with `openssl` and it must be the same for all client applications that want to use this authentication service.


Clone this repository:
```
cd $HOME/dev
git clone https://github.com/OpenArCloud/openvps.git
```

Clone HLOC:
```
cd $HOME/dev/openvps
git clone https://github.com/cvg/Hierarchical-Localization.git
cd Hierarchical-Localization
git checkout abb2520 # 2024-11-03, compatible with pycolmap<=3.11
git checkout 2e2a551 # 2025-07-22, compatible with pycolmap>=3.12,<4.0
git checkout c13273b # 2025-12-10, compatible with pycolmap==3.13,<4.0
git submodule update --init --recursive
```

Write a `docker.env` configuration file based on this template:
```sh
# -- Common configuration
# Network proxy as http://<host>:<port> (default empty)
MY_HTTP_PROXY=
MY_HTTPS_PROXY=

# User and group id of your host user if you want to be able to read/write the map files outside docker. You can get these by the 'id' command in the host Ubuntu
MY_USER_ID=1000
MY_GROUP_ID=1000

# Shared folder where maps are stored (default ${HOME}/data/maps)
MY_SHARED_MAPS_DIR=${HOME}/data/maps

# Auth.JS env variables
AUTH_FUSIONAUTH_ID=
AUTH_FUSIONAUTH_SECRET=
AUTH_FUSIONAUTH_ISSUER=https://your.domain.name:your_external_auth_port
AUTH_SECRET=


# -- MapBuilder (frontend) configuration
# This is the port that you can access on localhost. The 'frontend' container listens on these two ports.
MAPBUILDER_URL=https://your.domain.name:your_external_mapbuilder_frontend_port
MAPBUILDER_PORT=80
MAPBUILDER_PORT_HTTPS=443

# -- MapAligner configuration
# This is the port that you can access on localhost. The 'mapaligner' container listens on this port.
MAPALIGNER_PORT=your_host_mapaligner_port
# This is your external URL from the Internet, assuming that you configured NGINX to map from your_external_mapaligner_port to your_internal_mapaligner_port
MAPALIGNER_URL=https://your.domain.name:your_external_mapaligner_port

# -- MapLocalizer (GPU service; host bind for admin / debugging only)
# MAPLOCALIZER_URL is not set in docker.env: compose injects http://maplocalizer:8000 for in-cluster callers (MapBuilder backend, MapSelector).
MAPLOCALIZER_PORT=your_host_maplocalizer_port

# -- MapRegistry (coverage index; localhost debugging)
MAPREGISTRY_PORT=your_host_mapregistry_port

# -- MapSelector (public GeoPoseProtocol endpoint; entry for AR clients)
MAPSELECTOR_PORT=your_host_mapselector_port
MAPSELECTOR_URL=https://your.domain.name:8046
```

### NGINX and GeoPoseProtocol

Previous OpenVPS versions terminated TLS on port **8046** and proxied to **MapLocalizer**. Multi-map OpenVPS keeps the **same public port and path** (`POST /localize/geopose`) but the upstream must be **MapSelector**, not MapLocalizer.

| Traffic | Public (nginx) | Docker upstream |
|---------|----------------|-----------------|
| AR clients, spARcl, GPP | `https://your.domain:8046` → host `MAPSELECTOR_PORT` | `mapselector:8102` |
| MapBuilder “load map” pin, `current_map_id` | *(not via 8046)* | In-cluster `http://maplocalizer:8000` (compose sets **`MAPLOCALIZER_URL`** on the backend only) |
| MapRegistry debugging | Optional `8044` on localhost/VPN | `mapregistry:8101` |
| Direct MapLocalizer (debug) | Optional `8043` — do **not** publish to the Internet | `maplocalizer:8000` |

Example host nginx (TLS on 8046 → internal MapSelector bind):

```nginx
# HTTPS server listening on external port 8046
location / {
    proxy_pass http://127.0.0.1:18046;   # MAPSELECTOR_PORT in docker.env (host side)
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50m;            # GeoPose image payloads
    proxy_read_timeout 600s;             # cold map load + first localize can be slow
    proxy_send_timeout 600s;
}
```

**Do not** point 8046 at MapLocalizer anymore. MapLocalizer admin routes (`/load_map/…`, `/current_map_id`, …) stay on the internal URL; MapBuilder already uses that URL from compose.

Client base URL in app configs should use **`MAPSELECTOR_URL`** (same hostname/port as before if you only change the proxy target).

For example, let us assume that the domain name of your OpenVPS is `https://openvps.org` and the following _external_ ports are used:
- 8045 for FusionAuth
- 8046 for MapSelector (GeoPose; public client entry)
- 8047 for MapBuilder
- 8048 for MapAligner
- 8043 for MapLocalizer (optional; direct service access)
- 8044 for MapRegistry (optional; index debugging)

These ports need to be forwarded from your router to your host machine. You need to adapt in the `docker.env` file the internal ports where the actual services are running on your host machine. If you also use nginx for port mapping on the host machine, the internal service ports cannot be the same as the external ports.

For example, let us assume that the following _internal_ ports are used:
- 18045 for FusionAuth
- 18046 for MapSelector
- 18043 for MapLocalizer
- 18044 for MapRegistry
- 18047 for MapBuilder
- 18048 for MapAligner

The corresponding example configuration is shown below:
```
MAPALIGNER_PORT=18048
MAPALIGNER_URL=https://openvps.org:8048
MAPBUILDER_PORT=18047
MAPBUILDER_PORT_HTTPS=18443
MAPBUILDER_URL=https://openvps.org:8047
MAPLOCALIZER_PORT=18043
MAPREGISTRY_PORT=18044
MAPSELECTOR_PORT=18046
MAPSELECTOR_URL=https://openvps.org:8046
```

Make sure to configure FusionAuth to accept your actual request and redirect URLs. See [README-FusionAuth.md](/README-FusionAuth.md).



Start all services:
```sh
docker compose --env-file docker.env --progress=plain build
docker compose --env-file docker.env --progress=plain up
```

Stop services:
```sh
docker compose --env-file docker.env --progress=plain down
```

Run a single container for testing:
```sh
docker run --rm -it --gpus all openvps-backend:latest /bin/bash
```

## Usage

### Recording
Once you got your OpenVPS services running, you will need to create your first map. Our first version supports map creation from iOS RGBD+pose recordings, which can be recorded with the free and open [StrayScanner](https://docs.strayrobots.io/) app. Record a sequence while making sure that you move slowly, you cover the building facades from a distance, and you make loops in your trajectory. Do not go too close to objects, avoid textureless areas, avoid shiny and mirroring surfaces like glass, and do not rotate the phone in one place. At the beginning, we recommend to experiment with recordings of about 1 minute in length.

### Upload
Once you recorded a sequence, go to the iOS Files app on your phone, find the files on your phone, and the StrayScanner folder within. Select your recording's folder and compress it to a zip file. Open your mapbuilder URL in Safari, log in, and upload your zip file. This may take up to a few minutes depending on your connection speed and the size of the recording.

### MapBuilder
Once you uploaded your image sequence dataset, it will get a unique ID assigned, it gets extracted, the video gets converted to an image sequences, the images get resized and rotated, and a thumbnail gets assigned to the dataset. Now you can start the map building process by pressing the play button. This might take around 10-30 minutes depending on the size of your recording.

### MapAligner
Once the map is built, more buttons will appear in the dataset's GUI. Next, you need to align the map with the world by clicking on the cross arrows icon, which opens the MapAligner with the corresponding map. First you need to define the coarse location by navigation the map view to your mapped street. Open the 'set georeference origin' panel and check 'set georeference origin with click'. Click on any point that you want to be the reference of the alignment, it can be any point in the neighborhood. Next, perform the map alignment with the gizmo. You can adjust the scale with the sliders in the left side menu. Finally, press the big green save button, this writes the transform to the MapBuilder.

### MapLocalizer
Once your map is aligned with the world, it is ready to be served in the MapLocalizer. Click on the localization pin icon of the dataset's GUI, which loads the map into the MapLocalizer. This might take up to 30 seconds depending on the map size. Once the map is loaded, send GeoPoseRequest queries to **MapSelector** at `MAPSELECTOR_URL` + `/localize/geopose` (default public port **8046**). MapSelector picks the map from coarse GNSS when multiple maps are deployed.

### VPS Queries
You can find example clients in Open AR Cloud repositores based on a WebXR client in [spARcl](https://github.com/OpenArCloud/sparcl), a Cesium client in [cesium-viewer](https://github.com/OpenArCloud/cesium-viewer), and C++ and Python console clients in [oscp-geopose-protocol](https://github.com/OpenArCloud/oscp-geopose-protocol).

The camera intrinsics are also required in the queries. If you send queries via spARcl, it submits the camera intrinsics automatically. If you use other clients, you need to find out somehow the intrinsics. The stock Android Photo app writes them into the EXIF metadata of the photos, you can read those out. You can also use images from StrayScanner recordings as queries (same sequence as for mapping or other recording, does not matter), because StrayScanner also saves the intrinsics. The Cesium client reads the intrinsics from the EXIF. The C++ and Python clients take the intrinsics from a JSON file that the user needs to write before the query.


## Troubleshooting

### ERROR: Unexpected bus error encountered in worker. This might be caused by insufficient shared memory (shm)

Increase `shm_size` in docker-compose.yml (backend and maplocalizer service)

### Unable to verify leaf signature

Add `NODE_TLS_REJECT_UNAUTHORIZED=0` environment variable to backend and mapaligner service in docker-compose.yml

### [auth][error] TypeError: fetch failed

The identity provider cannot be reached due to either a connection issue or the TLS error above. If self-hosted, check if it is running

### FusionAuth login error
We found that the FusionAuth container sometimes dies and this results in a misconfiguration error message on the login screen. In this occurs, restart the FusionAuth container.

### Docker image and GPU driver incompatibility
nvidia CUDA Docker images: https://gitlab.com/nvidia/container-images/cuda/-/blob/master/doc/supported-tags.md?ref_type=heads

### Pytorch and GPU driver version incompatibility
Minimum and Maximum CUDA capability supported by Pytorch depends on the version. If your GPU is older, you may need to downgrade the `torch` package that HLOC installs automatically. There is a commented section in the MapBuilder and MapLocalizer Dockerfiles for that.

If you see PyTorch UserWarning: CUDA initialization: The NVIDIA driver on your system is too old (found version xxxx)...
Replace PyTorch with an earlier version if your GPU is not supported by the newest version by adding these two lines to the Dockerfile of mapbuilder-backend and maplocalizer:
```
RUN pip uninstall torch -y
RUN pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1
```

When updating the host GPU drivers, there might be need to update the nvidia/cuda base images too. This command ensures to download the latest image and check the GPU compatibility: `docker run --rm --gpus all nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 nvidia-smi` (or whichever base container is used in the subproject Dockerfiles). If the base image gets updated, you also need to rebuild the OpenVPS images.


## Known issues and feature ideas:
 - The map height is not real altitude but above ground
 - Only one map can be active at a time (sufficient for educational purposes)
 - MapBuilder should have datasets and maps separated from each other, because from one dataset we could create multiple maps by using different HLOC methods and/or parameters.
 - Support for selecting various HLOC configs on the frontend
 - Metric alignment fails if there are less than 4 shared images, which is abnormal. This occurs when the colmap model is broken into multiple pieces, and there is a bug in HLOC that may accidentally return a small model instead of the largest model. Use our fix [here](https://github.com/cvg/Hierarchical-Localization/pull/504)
 - DIR image retrieval in HLOC is currently not working because the model is no longer available in [GDrive](https://drive.google.com/uc?id=1UWJGDuHtzaQdFhSMojoYVQjmCXhIwVvy
 )
 