# Map localizer
Visual localization server using the Open AR Cloud GeoPoseProtocol. The server relies on [HLOC](https://github.com/cvg/Hierarchical-Localization) for localization. It loads a map created by the MapBuilder (HLOC) and localizes query images in it. The queries can be sent for example from a smartphone.

This component is part of OpenVPS: Open Visual Positioning Service.

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
pip install --no-cache-dir --verbose \
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
```
The uploadsDir should point to the folder where your mapbuilder puts the maps.


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
