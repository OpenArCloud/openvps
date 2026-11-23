# Map localizer
Visual localization server using the Open AR Cloud GeoPoseProtocol. The server relies on [HLOC](https://github.com/cvg/Hierarchical-Localization) for localization. It loads a map created by the MapBuilder (HLOC) and localizes query images in it.

This component is part of OpenVPS: Open Visual Positioning Service.

**AR clients** should call **[MapSelector](../mapselector/README.md)** (`MAPSELECTOR_URL`, default public port **8046**) for `POST /localize/geopose`, not MapLocalizer directly. MapSelector picks a map from GNSS via MapRegistry and proxies to MapLocalizer with `X-OpenVPS-Map-Id`.

**MapBuilder** still talks to MapLocalizer on the **in-cluster** URL (`http://maplocalizer:8000` in compose, or host port **8043** when debugging) for `GET /current_map_id` and `GET /load_map/{mapId}`.

Author: Gabor Soros (@soeroesg)


# Local setup
Note that a docker compose file is provided in the main repository. Local setup is only required if you want to modify the code.

## Hierarchical-Localization
Clone Hierarchical-Localization next to the maplocalizer code.
Use a specific commit version below.
```
cd maplocalizer/..
git clone https://github.com/cvg/Hierarchical-Localization.git
cd Hierarchical-Localization
git checkout abb252080282e31147db6291206ca102c43353f7
git submodule update --init --recursive
```

## Python virtual environment
```
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

Install HLOC:
```
pip install -e ../../Hierarchical-Localization
```

Install FastAPI. Note: Make sure you put "fastapi[standard]" in quotes to ensure it works in all terminals.
```
pip install "fastapi[standard]"
pip install pydantic-settings
```

## Environment
If you want to run the server without Docker, create `server/.env` file with the following content:
```
appName="OpenVPS-MapLocalizer"
uploadsDir=/path/to/your/maps/folder
debug=False
maxLoadedMaps=1
```
The uploadsDir should point to the folder where your mapbuilder puts the maps.

**Image retrieval:** When `config.yaml` sets `retrieval_conf`, online localization needs **`global_features.h5`** next to `features.h5` under `reconstruction_path`. **New MapBuilder runs** also write `global_features.h5` for `from_poses` / `from_exhaustive` maps (extra global-descriptor pass after local features). **Legacy maps** built before that change may lack the file — MapLocalizer refuses the old “match every image” fallback and returns a clear error instead.

**Fix an existing map (e.g. `from_poses`):** Re-run the MapBuilder HLOC pipeline at least through **`hloc_extract_features`** (and keep `retrieval_conf` in the map config), or copy a completed map’s layout from a freshly built one. Confirm `hloc_reconstruction/global_features.h5` exists before relying on MapSelector auto-load.

**Multi-map GPU policy:** `maxLoadedMaps` caps how many maps stay resident (default **1**). Before loading a map, MapLocalizer derives **`localization_model_signature`** from `config.yaml` (`feature_conf`, `matcher_conf`, `retrieval_conf`, `pairs_strategy`). Maps with a **different** signature are unloaded first so only one HLOC neural stack is on the GPU at a time. With `maxLoadedMaps>1`, only maps sharing the same signature may remain loaded together. The signature is also written to `coverage.json` at coverage compute time for the registry index.


# Running the server
To run on a specific GPU:
```
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

Start FastAPI:
```
fastapi run server/main.py --proxy-headers
```
