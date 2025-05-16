# Map aligner

With this tool, point clouds from the MapBuilder service can be loaded and manually aligned to OpenStreetMap buildings. The resulting 3D transform matrix can be saved into MapBuilder or exported/imported in JSON format.

This component is part of OpenVPS: Open Visual Positioning Service.

Authors: Andor Kovacs (@KovacsA22), Gabor Soros (@soeroesg)


# Local setup
Note that a docker compose file is provided in the main repository. Local setup is only required if you want to modify the code.

## Local setup without Docker
Install dependencies:
```bash
npm install
```

Create a `.env` file as below.

Run the server:

```bash
npm run dev
```

Open [http://localhost:3001](http://localhost:3001) in your browser to see the result.


## Deploy with Docker

1. Create a `.env` file with the following variables:

```
PORT=

# FusionAuth settings
AUTH_FUSIONAUTH_ID=
AUTH_FUSIONAUTH_SECRET=
AUTH_FUSIONAUTH_ISSUER=

# URL of mapbuilder to fetch the maps
MAPBUILDER_URL=

# Default start location
NEXT_PUBLIC_DEFAULT_LATITUDE=
NEXT_PUBLIC_DEFAULT_LONGITUDE=
NEXT_PUBLIC_DEFAULT_HEIGHT=
```

2. Generate Auth.js secret (must be the same for MapBuilder and MapAligner)

```
echo "AUTH_SECRET=$(openssl rand -base64 33)" >> .env
```

3. Run `docker compose build`

4. Run `docker compose up`


# Third-party libraries
Uses the [NextJS](https://nextjs.org/) framework, rendering is done with [react-three-map](https://github.com/RodrigoHamuy/react-three-map) and UI components are from [DaisyUI](https://daisyui.com/).

Currently uses [Auth.JS](https://authjs.dev/) for authentication and [FusionAuth](https://fusionauth.io/) as a self-hostable identity provider, but other providers can also be added by editing the `lib/auth.js` file and adding the corresponding environment variables.
