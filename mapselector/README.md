# Map Selector

OpenVPS public GeoPoseProtocol server. Clients call **`POST /localize/geopose`** here instead of MapLocalizer directly.

## Flow

1. Derive a WGS84 query point: **`priorPoses[0]`** (`geopose.position` or `geoposes[0].position`) takes priority, else **`sensorReadings.geolocationReadings[0]`**. FramedPose-only priors (`poses[]` without WGS84) are ignored for map selection.
2. Call MapRegistry **`GET /maps/query`** (`lat`, `lon`, `radius_m`; default horizontal radius **75 m**, raised by prior **`accuracy.position`** or GNSS **`accuracy`** when > 1 m). Optional **`alt`** / **`alt_radius_m`** when **`kEnableVerticalSearch`** is `True` (default **off**; **15 m** vertical window).
3. Pick one or more ranked `map_id` candidates.
4. Proxy the request to MapLocalizer with header **`X-OpenVPS-Map-Id`**.

With neither prior nor GNSS hint, MapSelector forwards **without** `X-OpenVPS-Map-Id` (currently loaded map). With a hint but no registry hit, HTTP 404.

## Multi-map try (feature under development)

Bounded multi-map retries are controlled by module constants in `server/main.py`: **`kEnableMultiMapLocalization`** and **`kMultiMapMaxNumCandidates`** (defaults: `False`, `1` — top candidate only). When enabled in code, MapSelector attempts localization on up to **`kMultiMapMaxNumCandidates`** ranked candidates until MapLocalizer returns HTTP 200 with a GeoPose payload (or a non-retryable error). Response headers:

- **`X-OpenVPS-Map-Id`** — map used for the successful attempt (or last attempt)
- **`X-OpenVPS-Maps-Tried`** — comma-separated map ids attempted

## Configuration

**Public (AR clients):** configure **`MAPSELECTOR_URL`** in `docker.env` (e.g. `https://your.domain:8046`). Host bind: **`MAPSELECTOR_PORT`** (default **8046**). Host nginx must proxy **8046 → MapSelector**, not MapLocalizer (see root [`README.md`](../README.md) — **NGINX and GeoPose**).

**In-cluster only:** Compose sets **`MAPLOCALIZER_URL=http://maplocalizer:8000`** and **`MAPREGISTRY_URL=http://mapregistry:8101`** for MapSelector. Do not point these at public HTTPS URLs from `docker.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAPSELECTOR_URL` | *(operator-defined)* | Public GeoPose base URL for clients |
| `MAPSELECTOR_PORT` | `8046` | Host port published to MapSelector (container **8102**) |
| `MAPREGISTRY_URL` | `http://mapregistry:8101` | Registry base URL (in-cluster) |
| `MAPLOCALIZER_URL` | `http://maplocalizer:8000` | MapLocalizer base URL (in-cluster) |

Registry query tuning in `server/selection.py`: **`kDefaultHorizontalSearchRadius`** (75), **`kEnableVerticalSearch`** (default `False`), **`kDefaultVerticalSearchRadius`** (15).
