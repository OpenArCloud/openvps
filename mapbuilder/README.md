# Map builder
Frontend and backend server code for creating visual positioning maps with the [Hierarchical Localization](https://github.com/cvg/Hierarchical-Localization) framework. The input data can come from [StrayScanner](https://docs.strayrobots.io/) RGBD recordings.

This component is part of OpenVPS: Open Visual Positioning Service.

Authors: Denes Bisztray (@bisztray), Andor Kovacs (@KovacsA22), Gabor Soros (@soeroesg)

# Local setup
Note that a docker compose file is provided in the main repository. Local setup is only required if you want to modify the code.

## Hierarchical-Localization
Clone Hierarchical-Localization next to the mapbuilder code.
Use a specific commit version below.
```
cd mapbuilder/..
git clone https://github.com/cvg/Hierarchical-Localization.git
cd Hierarchical-Localization
git checkout abb252080282e31147db6291206ca102c43353f7
git submodule update --init --recursive
```

## Python virtual environment
```
cd Backend
python3 -m venv .venv
. .venv/bin/activate
pip install --verbose \
    numpy \
    pyyaml \
    ruamel.yaml \
    matplotlib \
    opencv-python \
    opencv-contrib-python \
    transforms3d
```

Install hloc
```
pip install -e ../../Hierarchical-Localization
```

Install additional dependencies of r2d2 and dir submodules of hloc
```
pip install --verbose \
    pillow \
    scikit-learn
```

## Authentication
We use FusionAuth for authentication to protect the maps. Download and run FusionAuth locally in Docker. See the main OpenVPS documentation for configuring FusionAuth.

## Backend Setup
The code was developed and tested with NodeJS 22.

Adapt your backend port in `service.ts`.

Install the dependencies:
```
cd Backend
npm install
```

Create an environment file `Backend/.env` similar to:
```
uploadsDir=/home/username/data/uploads
scriptsDir=/home/username/dev/openvps/mapbuilder/scripts_mapping
hlocDir=/home/username/dev/openvps/Hierarchical-Localization
shell=bash

AUTH_FUSIONAUTH_ID=
AUTH_FUSIONAUTH_SECRET=
AUTH_FUSIONAUTH_ISSUER=
AUTH_SECRET=

MAPLOCALIZER_URL=http://localhost:8043
MAPREGISTRY_URL=http://localhost:8044
```

See `Backend/.env.example` for full comments (in-cluster URLs, operator-only `MAPSELECTOR_*`).

When `MAPREGISTRY_URL` is set, MapBuilder writes `coverage.json` under each `hlocMaps/<mapId>/` directory (via `compute_map_coverage.py`) after the HLOC **Coverage** pipeline stage and after saving a map **transform**, then calls MapRegistry `POST /internal/reload` so the registry re-ingests that map.

The localization pin in the UI calls MapLocalizer via **`MAPLOCALIZER_URL`** (in-cluster / host port **8043**), not MapSelector. AR clients use **`MAPSELECTOR_URL`** on port **8046** (see root README **NGINX and GeoPose**).

`coverage.json` includes **`localization_model_signature`** (from map `config.yaml`) for MapRegistry / multi-map GPU policy.

Coverage footprints use **filtered COLMAP points3D** (track length, reprojection error, horizontal distance-to-cameras), then a **convex hull** in lon/lat. The **Coverage** HLOC run stage in the MapBuilder GUI exposes the same parameters as `compute_map_coverage.py` (preset, track length, reprojection error, horizontal radius, percentile).

Run coverage filter unit tests: `python -m pytest mapbuilder/scripts_mapping/test_coverage_points.py`

Run the server:
```
cd Backend
. .venv/bin/activate
npx tsx src/index.ts
```

## Frontend Setup
Adapt your frontend port and backend IP and port in `vite.config.ts`:
```
server: {
    port: 8047,
    proxy: {
      ...
    }
  }
```

Then install the dependencies
```
cd Frontend
npm install
```

And run the server:
```
cd Frontend
npm run dev -- --host
```

# Third-party libraries
The backend relies on the [Hierarchical Localization](https://github.com/cvg/Hierarchical-Localization) framework for building point cloud maps.

The Frontend uses [shadcn-svelte component library](https://www.shadcn-svelte.com/)
The files under `Frontend/src/lib` are from shadcn-svelte.
Shadcn-svelte components are added as needed, see [instructions](https://www.shadcn-svelte.com/docs/installation/sveltekit)
Example commmand to add the button component `npx  shadcn-svelte@latest add button`

Do not add any of our own files under `Frontend/src/lib`.
This way we can delete and recreate this directory as needed, not impacting our codes.

Icons are from [Phosphor Icons](https://phosphoricons.com/) (regular version).
Change `<svg>` tag attributes to `width="24" height="24" fill="currentColor"` after importing a new one.
