# OpenVPS

Open Visual Positioning Service - Main repository with build scripts and documentation. The project was funded by [NGI Search](https://www.ngisearch.eu/view/Events/OC5Searchers) EU Project and [Open AR Cloud](https://www.openarcloud.org/), 2025.

Authors: Andor Kovacs (@KovacsA22), Denes Bisztray (@bisztray), Gabor Soros (@soeroesg)

Copyright 2025 Nokia
Licensed under the MIT License.
SPDX-License-Identifier: MIT


## Modules
The system consists of 4 main components: MapBuilder, MapAligner, MapLocalizer, and the [HLOC](https://github.com/cvg/Hierarchical-Localization) third-party mapping and localization framework. Authentication via [FusionAuth](https://fusionauth.io/) is used to protect the maps.

First, images are captured by a smartphone app (currently the format of [StrayScanner](https://docs.strayrobots.io/) is supported), and uploaded to the MapBuilder for processing. The MapBuilder runs the HLOC mapping pipeline, and the map points are also exported as a PLY point cloud. The MapAligner loads the PLY point cloud and an OpenStreetMap map tile, and the user manually aligns the point cloud with the building footprints on the map. The resulting 3D transform can be saved to the MapBuilder. Finally, a map with its transform can be loaded into the MapLocalizer, which can then localizes query images sent by mobile devices. The localization happens in the HLOC map first, but using the geo-alignment transform, the result is converted to OGC GeoPose format.

![System overview](./docs/overview.jpg)


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


### Authentication
We use FusionAuth for authentication to protect the maps. Download and run FusionAuth locally in Docker. See [this](/docs/FusionAuth.md) documentation on how to configure FusionAuth.


## Setup

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
git checkout abb252080282e31147db6291206ca102c43353f7
git submodule update --init --recursive
```

Write a `docker.env` configuration file based on this template:
```sh
# -- Common configuration
# Network proxy as http://<host>:<port> (default empty)
MY_HTTP_PROXY=
MY_HTTPS_PROXY=

# User ID and Group ID for shared files and directories (default 1000:1000)
MY_USER_ID=1000
MY_GROUP_ID=1000

# Default reference point in geo coordinates
DEFAULT_LONGITUDE=
DEFAULT_LATITUDE=
DEFAULT_HEIGHT=0

# Shared folder where maps are stored (default ${HOME}/data/maps)
MY_SHARED_MAPS_DIR=${HOME}/data/maps

# Auth.JS env variables
AUTH_FUSIONAUTH_ID=
AUTH_FUSIONAUTH_SECRET=
AUTH_FUSIONAUTH_ISSUER=
AUTH_SECRET=


# -- MapBuilder configuration

# Frontend port configuration (default 80 and 443)
MAPBUILDER_PORT=80
MAPBUILDER_PORT_HTTPS=443

# -- MapAligner configuration

# Port configuration
MAPALIGNER_PORT=your_internal_mapaligner_port
MAPALIGNER_URL=https://your.domain.name:your_external_mapaligner_port

# -- MapLocalizer configuration

# Port configuration
MAPLOCALIZER_PORT=your_internal_maplocalizer_port
```


For example, let us assume that the domain name of your OpenVPS is `https://openvps.org` and the following _external_ ports are used:
- 8045 for FusionAuth
- 8046 for MapLocalizer
- 8047 for MapBuilder
- 8048 for MapAligner

These ports need to be forwarded from your router to your host machine. You need to adapt in the `docker.env` file the internal ports where the actual services are running on your host machine. If you also use nginx for port mapping on the host machine, the internal service ports cannot be the same as the external ports.

For example, let us assume that the following _internal_ ports are used:
- 18045 for FusionAuth
- 18046 for MapLocalizer
- 18047 for MapBuilder
- 18048 for MapAligner

The corresponding example configuration is shown below:
```
MY_HTTP_FRONTEND_PORT=18047
MY_HTTPS_FRONTEND_PORT=18443

MAPALIGNER_PORT=18048
MAPALIGNER_URL=https://openvps.org:8048
#MAPBUILDER_PORT=18047
MAPBUILDER_URL=https://openvps.org:8047
MAPLOCALIZER_PORT=18046
MAPLOCALIZER_URL=https://openvps.org:8046
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


## Troubleshooting

### ERROR: Unexpected bus error encountered in worker. This might be caused by insufficient shared memory (shm)

Increase `shm_size` in docker-compose.yml (backend and maplocalizer service)

### Unable to verify leaf signature

Add `NODE_TLS_REJECT_UNAUTHORIZED=0` environment variable to backend and mapaligner service in docker-compose.yml

### [auth][error] TypeError: fetch failed

The identity provider cannot be reached due to either a connection issue or the TLS error above. If self-hosted, check if it is running
