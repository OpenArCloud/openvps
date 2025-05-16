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
pip install --no-cache-dir --verbose \
    numpy \
    pyyaml \
    ruamel.yaml \
    matplotlib \
    opencv-python \
    opencv-contrib-python \
    transforms3d
```

Install HLOC
```
pip install -e ../../Hierarchical-Localization
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

DEFAULT_LONGITUDE=
DEFAULT_LATITUDE=
DEFAULT_HEIGHT=

MAPLOCALIZER_URL=
```

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
