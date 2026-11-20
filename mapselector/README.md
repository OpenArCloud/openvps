# Map Selector

OpenVPS public GeoPoseProtocol server. Clients call **`POST /localize/geopose`** here instead of MapLocalizer directly. Legacy MapLocalizer probes on the old public port are proxied in-cluster: **`GET /current_map_id`**, **`GET /health`**, **`GET /gpu_info`**. MapSelector-only liveness: **`GET /ready`**, **`GET /`**.

## Flow

1. Derive a WGS84 query point: **`priorPoses[0]`** (`geopose.position` or `geoposes[0].position`) takes priority, else **`sensorReadings.geolocationReadings[0]`** (also accepts **`geoLocationReadings`**, as some clients serialize). FramedPose-only priors (`poses[]` without WGS84) are ignored for map selection.
2. Call MapRegistry **`GET /maps/query`** (`lat`, `lon`, `radius_m`; default horizontal radius **75 m**, raised by prior **`accuracy.position`** or GNSS **`accuracy`** when > 1 m). Optional **`alt`** / **`alt_radius_m`** when **`kEnableVerticalSearch`** is `True` (default **off**; **15 m** vertical window).
3. Pick one or more ranked `map_id` candidates.
4. Proxy the request to MapLocalizer with header **`X-OpenVPS-Map-Id`**.

With neither prior nor GNSS hint, MapSelector forwards **without** `X-OpenVPS-Map-Id` (currently loaded map). If no map is loaded, it returns **404** `Could not localize request …` **without** calling MapLocalizer. With a hint but no registry hit, HTTP 404.

## Multi-map try (feature under development)

Bounded multi-map retries are controlled by module constants in `server/main.py`: **`kEnableMultiMapLocalization`** and **`kMultiMapMaxNumCandidates`** (defaults: `False`, `1` — top candidate only). When enabled in code, MapSelector attempts localization on up to **`kMultiMapMaxNumCandidates`** ranked candidates until MapLocalizer returns HTTP 200 with a GeoPose payload (or a non-retryable error). Response headers:

- **`X-OpenVPS-Map-Id`** — map used for the successful attempt (or last attempt)
- **`X-OpenVPS-Maps-Tried`** — comma-separated map ids attempted

## Configuration

**Public (AR clients):** configure **`MAPSELECTOR_URL`** in `docker.env` (e.g. `https://your.domain:8046`). Host bind: **`MAPSELECTOR_PORT`** (default **8046**). Host nginx must proxy **8046 → MapSelector**, not MapLocalizer (see root [`README.md`](../README.md) — **NGINX and GeoPose**).

**In-cluster only:** Compose sets **`MAPLOCALIZER_URL=http://maplocalizer:8000`** and **`MAPREGISTRY_URL=http://mapregistry:8101`** for MapSelector. Do not point these at public HTTPS URLs from `docker.env`. MapSelector uses **`httpx` with `trust_env=False`** for those calls so a host **`HTTP_PROXY`** (e.g. `MY_HTTP_PROXY` for image builds) is not used for `maplocalizer` / `mapregistry` DNS names.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAPSELECTOR_URL` | *(operator-defined)* | Public GeoPose base URL for clients |
| `MAPSELECTOR_PORT` | `8046` | Host port published to MapSelector (container **8102**) |
| `MAPREGISTRY_URL` | `http://mapregistry:8101` | Registry base URL (in-cluster) |
| `MAPLOCALIZER_URL` | `http://maplocalizer:8000` | MapLocalizer base URL (in-cluster) |

Registry query tuning in `server/selection.py`: **`kDefaultHorizontalSearchRadius`** (75), **`kEnableVerticalSearch`** (default `False`), **`kDefaultVerticalSearchRadius`** (15).

## Troubleshooting `POST /localize/geopose`

Responses use GPP-style JSON: `{"ERROR": "..."}` when MapSelector fails before or instead of a GeoPose result. Check **`docker compose logs mapselector`** for lines like `map resolution failed` or `map resolve via registry` / `via loaded map`.

| Symptom | Typical cause |
|---------|----------------|
| **404** `Could not localize request …` + no MapLocalizer **POST** log | No location hint and **no map loaded** — same client-facing failure as MapLocalizer; load a map in MapBuilder first. |
| **502** `MapRegistry unreachable` / `MapLocalizer unreachable` | In-cluster network or service down; confirm `mapregistry` / `maplocalizer` containers are up. |
| **404** `No map coverage intersects coarse location` | Real GNSS/prior but no indexed coverage at that point — (re)compute coverage in MapBuilder or load the map manually. |
| Client sends **`geolocationReadings`** at **(0,0)** | Treated as no hint (placeholder); falls back to the **loaded map** in MapLocalizer — use MapBuilder’s load-map pin first. |
