# MapRegistry

Ingest-only coverage index for OpenVPS multi-map selection. Reads per-map **`coverage.json`** (written by MapBuilder).

Docker Compose maps **`MAPREGISTRY_PORT`** (default **8044** on the host) to container port **8101** for local inspection (`GET /health`, `GET /maps`, `GET /maps/query`). In-cluster callers use `http://mapregistry:8101` (set via compose; not overridden from `docker.env`).

## Map identity

- **Canonical key:** global **`map_id`** (MapBuilder UUID = `hlocMaps/{mapId}/` directory name). Index keys, `GET /maps/query` candidates, and `X-OpenVPS-Map-Id` all use this id.
- **`dataset_id`:** which upload folder owns the map (`uploads/{dataset_id}/`); used to validate `POST /internal/reload` only—not exposed to AR clients.
- **Duplicates:** the same `map_id` under two datasets is reported in startup/rescan `errors`; the index keeps one entry (last wins in sorted dataset name order).

## Layout

- `server/main.py` — FastAPI: startup rescan, `GET /maps`, `GET /maps/query`, `POST /internal/reload`, `POST /internal/rescan`
- `server/map_catalog.py` — enumerate `uploads/{dataset}/hlocMaps/{mapId}`
- `server/coverage_schema.py` — `MapCoverageRecord`, artifact parsers
- `server/ingest.py` — validate and store each map's `coverage.json` into `map_registry.json`
- `server/geo_query.py` — GNSS overlap for **`geo_query.strategy: standard`** only

## `coverage.json` v1 (ingested)

- `volumes[]`: metric `aabb` with `frame_ref`. Each map has at least one which is defined in its COLMAP coordinate frame.
- optional `geodetic_coverage`: `geo_aabb`, `geo_footprint` (`Polygon` | `MultiPolygon`). MultiPolygon is required for handling the two sides of the dateline (not implemented yet).
- optional `localization_model_signature`: HLOC NN stack id (see MapLocalizer multi-map policy).

## Query limits

**Supported:**  

- maps with |lat| ≤ 85 in `geo_aabb`: lon/lat/alt AABB prefilter, optional footprint point-in-polygon refine.

**Not supported:**

(ingest rejects geo block or MapBuilder should omit geo)

- Antimeridian (`crosses_antimeridian`, lon span > 180°)
- `geo_query.strategy` other than `standard` (antimeridian, high_latitude, polar_cap — reserved on artifact for future releases)
- High latitude (85-89) and polar caps (|lat| > 89)

