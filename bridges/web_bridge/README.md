# SpatialDDS Web Bridge

A FastAPI server that exposes the SpatialDDS bus to browsers and other HTTP/WebSocket
clients. Two generations of endpoints live in the same process:

| Surface | What it is | Who uses it |
|---|---|---|
| **Legacy** (`/v1/...`) | One-shot REST wrappers around localize + catalog, plus a fire-hose WebSocket. | The Cesium web demo under [`web/`](../../web/). Stable. |
| **Generic** (`/ws`, `/api/...`) | Subscribe-based protocol with topic patterns, optional `msg_type` filtering, server-side rate limiting, and browser-to-DDS publishing. | Any browser app that wants to listen to or talk to the SpatialDDS bus without hard-coded topics. |

Both are fed by one discovery-driven subscriber: it reads announces, resolves
each announced §3.3.2 type, and opens a typed reader per lane. Adding the
generic side doesn't double the DDS load.

**The bus carries types; the socket carries JSON.** Everything a WebSocket
client sees is serialised at this boundary. The `/ws` protocol is unchanged —
same message shape, same field names — but `msg_type` now holds the announced
registry type (`detection3d`, `framed_pose`) rather than a demo-private label,
which is strictly more information in the same place.

## Run

```bash
export SPATIALDDS_TRANSPORT=dds
export CYCLONEDDS_URI=file:///etc/cyclonedds.xml
export SPATIALDDS_DDS_DOMAIN=1
python3 bridges/web_bridge/server.py
```

Default port: 8088. Or via Docker (still recommended for the Cesium demo):

```bash
./run_bridge_server_docker.sh
# stop:
./stop_bridge_server_docker.sh
```

Logs land under `bridges/web_bridge/logs/`.

Environment knobs:

| Var | Default | Effect |
|---|---|---|
| `SPATIALDDS_DDS_DOMAIN` | (required) | CycloneDDS domain id |
| `SPATIALDDS_BRIDGE_ALLOW_PUBLISH` | `1` | Set to `0` to refuse all `publish` messages (read-only mode) |
| `SPATIALDDS_BRIDGE_STATIC_DIR` | `bridges/web_bridge/static` | Directory served at `/static` (debug dashboard lives there) |

## Spec discovery (`/.well-known/spatialdds/*`)

The bridge serves the spec's Layer 1.5 HTTP discovery binding, so a client with
no DDS stack can bootstrap, find services, and open a live stream over plain
HTTP:

| Endpoint | Returns |
|---|---|
| `GET /.well-known/spatialdds/bootstrap` | Bootstrap manifest (`spatialdds_bootstrap: "1.7"`), from `SPATIALDDS_BOOTSTRAP_*` config |
| `POST /.well-known/spatialdds/search` | `{"results": [<service manifest>, ...], "next_page_token": ""}` |
| `GET /.well-known/spatialdds/search?geohash=&kind=` | Same. §3.3.0 makes the GET form REQUIRED alongside POST, for the Geospatial DNS-SD binding, and defines it as equivalent to `POST {"geohash": ...}` — so it is implemented as exactly that body through the same call |

Search takes a CoverageQuery body and supports `filter`, the top-level `kind`
array, `max_results` and `page_token`. Results are ordered by `service_id`, so
paging is stable. There is no `query_id`: HTTP correlates request and response
itself, unlike the on-bus `CoverageResponse`.

The request table in §3.3.0 is not quite the on-bus `CoverageQuery` struct, and
the endpoint follows the table:

- `geohash` is a top-level shorthand, expanded to a bbox and added as an
  *additional* coverage element — so `{"geohash": "9q8yy"}` alone is a complete
  request, and a geohash alongside a coverage block widens the query.
- `coverage_frame_ref` is optional. It is not in the request table and appears
  in none of its examples; absent, the query is read as earth-fixed.
- Presence flags may be omitted, as the spec's own examples omit them:
  `{"crs": "EPSG:4326", "bbox": [...]}` is read as `has_bbox: true`. An
  explicit `false` is still honoured — inference applies only when the flag is
  missing. `has_circle` is never inferred, because `circle_center` is
  present-but-zero on anything that came off the bus.
- `expr` is rejected with a 400. 1.7 deleted it, and answering with the filter
  the caller believes is being applied would be worse than refusing.

Coverage matching is the full §3.3.4 model — `bbox`, `aabb` and `circle`, per
frame, with `global` on either side — and it is the same predicate the on-bus
`CoverageQuery` responder applies.

The semantics live in `spatialdds_demo/discovery_http.py`, shared with
`ar_demo/http_binding.py`. The two servers differ only in where their service
records come from.

`/.well-known/spatialdds/resolver` is not served.

### Translated to the bus, with the cache behind it

A search issues a real `CoverageQuery` on `spatialdds/discovery/query/v1` and
gathers the `CoverageResponse` each service sends back — the services decide
whether they cover the area, not the bridge. Two consequences worth knowing:

* **It takes a collection window** (~1.5 s). There is no completion signal in a
  one-to-many exchange, because a querier cannot know how many services exist.
* **The reply reader is KEEP_ALL, not the profile's KEEP_LAST(1).**
  `CoverageResponse` carries no `@key`, so every responder's reply lands on one
  instance; at depth 1 the last writer wins and the querier sees one service
  where several answered, with nothing to indicate loss.

The announce cache remains behind it, for detail and for fallback. A
`ServiceSummary` is deliberately compact, so topics and caps come from the
retained announce where one is held; where none is, the summary alone still
answers who covers the area. If nothing answers at all, the whole result comes
from the cache rather than reporting an empty deployment.

That makes cache freshness matter for detail rather than for existence. A
service leaves the cache when:

- **it departs** — a `DEPART` message evicts it immediately;
- **its announce expires** — entries older than `stamp + 2 x ttl_sec` are swept
  on the next read.

- **its instance is disposed** — `spatial::disco::Announce` is `@key
  service_id`, so NOT_ALIVE_DISPOSED names one service rather than the topic.

Dispose is the primary signal and the spec's MUST (C.5). `Depart` is the
SHOULD, and this demo publishes both, because a bridge to MQTT or a WebSocket
carries no DDS instance state — only a message crosses. TTL is the backstop
for a publisher that vanished without either. `GET /api/stats` reports the
cache counters.

### Serving authored manifests

If an announce's `manifest_uri` resolves to a manifest this deployment hosts,
that document is returned verbatim. Otherwise one is synthesized from the
announce, carrying across what the announce provides and omitting optional
fields rather than inventing them. Which path ran is logged, not signalled in
the response.

### Cold start with no SpatialDDS client code

[`scripts/cold_start.sh`](../../scripts/cold_start.sh) walks the whole Layer 1 →
1.5 → 2 path with curl and one `websocket-client` call: bootstrap, search a
geohash cell, read the topics off a returned manifest, subscribe on `/ws`, and
watch the exchange. Nothing in it imports the demo, the IDL, or CycloneDDS.

```
$ ./run_bridge_server_docker.sh          # bridge on :8088, VPS + catalogue behind it
$ scripts/cold_start.sh                  # BRIDGE=… GEOHASH=… to point it elsewhere

== 1. Bootstrap — which bus, and where
{"spatialdds_bootstrap":"1.7","domain_id":1,"initial_peers":["udpv4://127.0.0.1:7400"],
 "discovery_topic":"spatialdds/discovery/announce/v1","site":"sf-downtown",
 "manifest_uri":"spatialdds://vps.example.com/zone:sf-downtown/manifest:vps"}

== 2. Search — who covers geohash 9v6kr
1 service manifest(s), next_page_token=''
  svc:vps:demo/austin-downtown     VPS        spatialdds://vps.example.com/zone:austin-downtown/manifest:vps
      spatialdds/vps/query/v1          vps_query    VPS_REQ
      spatialdds/vps/result/v1         vps_response VPS_RESP

== 3. Pick a manifest and the topics it advertises
service:    svc:vps:demo/austin-downtown
subscribe:  spatialdds/vps/*
dds domain: 1  (from bootstrap — a manifest synthesized from an
                      announce carries no service.connection)

== 4. Subscribe over /ws, use the service, take the sample
-> {'type': 'subscribed', 'id': 'cold_start', 'pattern': 'spatialdds/vps/*', 'status': 'ok'}
-> curl -X POST http://127.0.0.1:8088/v1/localize -d {"service_id": "svc:vps:demo/austin-downtown"}
<- data on spatialdds/vps/query/v1 (vps_query)
   fields: query_id, service_id, client_frame_ref, has_prior_geopose, prior_geopose, ...
<- data on spatialdds/vps/result/v1 (vps_response)
   fields: query_id, service_id, status, has_node_geo, node_geo, confidence, has_rmse_m, rmse_m
   {"query_id": "8e0ca2be-…", "status": "VPS_SUCCESS", "has_node_geo": true, …}

== Cold start complete — bootstrap to live data, no SpatialDDS client code.
```

One thing in that transcript is worth knowing about:

- `service.connection` is absent from the manifest, so the domain id comes from
  bootstrap. An `Announce` has no connection block to carry and §8.2.3 makes
  the field OPTIONAL, so synthesis omits it rather than inventing one; §3.3.0
  nonetheless says clients "MUST be able to extract `service.connection` from
  any result", which a synthesized manifest cannot satisfy. Filed against 1.8.

## Legacy endpoints (the Cesium demo)

```
GET  /health                  → bridge status + last seen ANNOUNCE
POST /v1/localize             → Phase 3 LOCALIZE_REQUEST one-shot
POST /v1/catalog/query        → Phase 4 CATALOG_QUERY one-shot
WS   /v1/stream               → every received sample, no filtering
```

`/v1/localize` accepts `{ "prior_geopose": ..., "service_id": ... }` and returns
`spatial::argeo::VpsResponse` as JSON — `status` (a `VpsStatus` identifier),
`node_geo` behind `has_node_geo`, `confidence`, and `rmse_m` behind
`has_rmse_m`. `/v1/catalog/query` accepts a `geopose`, an optional `kind_in`
array and an optional `limit`; `expr` is refused with a 400, since 1.7 removed
it.

## Generic protocol (`/ws`)

JSON messages over WebSocket, identified by a `type` field.

### Client → server

```jsonc
// Subscribe (returns a "subscribed" ack)
{
  "type": "subscribe",
  "id": "sub_1",                                          // optional; auto-assigned otherwise
  "pattern": "spatialdds/*/sensing/detection3d/v1",       // glob on logical_topic
  "msg_types": ["detection3d"],                           // optional, AND-ed with pattern
  "max_rate_hz": 5.0                                      // optional server-side throttle
}

// Unsubscribe
{ "type": "unsubscribe", "id": "sub_1" }

// Publish back to the DDS bus. `msg_type` is resolved through the §3.3.2
// registry and the payload is built into that type before it is written, on
// the QoS profile §3.3.3 assigns it — so a malformed payload is refused here,
// with an error you can see, rather than becoming a well-formed message that
// fails somewhere else.
{
  "type": "publish",
  "msg_type": "framed_pose",
  "logical_topic": "spatialdds/web_client/ego/pose/v1",
  "payload": { "pose": { "t": {"x": 1, "y": 2, "z": 0}, "q": {"x": 0, "y": 0, "z": 0, "w": 1} } }
}

// Heartbeat / liveness probe
{ "type": "ping" }

// List active topics seen on the bus
{ "type": "list_topics" }
```

### Server → client

```jsonc
// Subscription confirmed
{ "type": "subscribed", "id": "sub_1", "pattern": "...", "status": "ok" }

// A relayed sample (one per message even if multiple of your subs match)
{
  "type": "data",
  "sub_id": "sub_1",
  "msg_type": "detection3d",
  "logical_topic": "spatialdds/operator_a/sensing/detection3d/v1",
  "timestamp_ns": 1714071012500000000,
  "payload": { ... }                  // SpatialDDS payload JSON, verbatim
}

// Topic discovery
{ "type": "topics", "topics": [ {logical_topic, msg_type, rate_hz, message_count, last_seen_ns}, ... ] }

// Heartbeat reply
{ "type": "pong", "server_time_ns": 1714..., "clients_connected": 3, "messages_dispatched": 1247 }

// Acks
{ "type": "unsubscribed", "id": "sub_1", "status": "ok" }
{ "type": "published",    "msg_type": "...", "logical_topic": "...", "status": "ok" }

// Error
{ "type": "error", "message": "...", "ref_id": "sub_1" }   // ref_id present when applicable
```

### REST helpers (no WebSocket required)

```
GET /api/topics           → { topics: [...] }
GET /api/topics?stale_threshold_s=120
GET /api/stats            → { uptime_s, clients_connected, total_dispatched, topics_active, dds_domain, publish_enabled }
```

## Browser client library

[`static/spatialdds-ws-client.js`](static/spatialdds-ws-client.js) is a ~120-line
zero-dep ES6 client. Auto-reconnects with a 2 s backoff, runs a 10 s ping.

```html
<script src="/static/spatialdds-ws-client.js"></script>
<script>
  const sdds = new SpatialDDSClient();          // ws://<host>/ws by default
  await sdds.connect();

  sdds.subscribe(
    "spatialdds/*/sensing/detection3d/v1",
    (msg) => console.log(msg.payload),
    { msgTypes: ["detection3d"], maxRateHz: 5 }
  );

  const topics = await sdds.listTopics();       // [{logical_topic, rate_hz, ...}]
</script>
```

## Built-in debug dashboard

If the bridge is running with the default static dir, hit `/static/index.html`
in a browser for a minimal topic browser + raw-message viewer. ~80 LOC of
vanilla HTML/JS. Useful for verifying which topics are live without wiring
up a real client.

## Architecture (discovery in, two fan-outs, typed out)

```
SpatialDDS bus
        │  announces on spatialdds/discovery/announce/v1  (@key service_id)
        ▼
  StreamSubscriber ── resolves each announced type through the 3.3.2 registry
        │             and opens one typed reader per lane
        │
        │  (poll thread; JSON serialisation happens here and only here)
        ▼
  _emit_dds_event ──► DDSEventBroadcaster ──► WS /v1/stream  (legacy)
        │
        └──► loop.call_soon_threadsafe(...)
                    │
                    ▼
              ClientManager.dispatch  ──► WS /ws  (generic, per-client filters)
                                       \─ TopicRouter (stats + rate limits)

  WS /ws  publish ──► _BrowserPublisher
                          │  resolves msg_type -> class, builds the payload
                          │  into it, writes on that type's 3.3.3 profile
                          ▼
                   SpatialDDS bus
```

Announces reach browsers under a per-service logical topic
(`spatialdds/{service}/discovery/announce/v1`) even though they are one keyed
topic on the bus. Browsers have subscribed with that wildcard since before the
announce topic was consolidated, so the bridge names the service in the logical
topic it hands out and the `/ws` protocol does not change.

The typed streaming layer is [`spatialdds_demo/stream.py`](../../spatialdds_demo/stream.py),
shared with the fusion demo, MCAP and MQTT, so QoS and type resolution stay
aligned across all of them.

## Tests

```bash
# Unit tests (no FastAPI, no DDS, no WebSocket — pure pytest)
python3 -m pytest -q bridges/web_bridge/test_router.py bridges/web_bridge/test_client.py

# Integration test (FastAPI TestClient WebSocket round-trip, no real DDS needed
# — drives ClientManager.dispatch directly from a synthetic sample source)
python3 -m pytest -q bridges/web_bridge/test_integration.py
```

## Sibling bridges

- [`bridges/mcap_bridge/`](../mcap_bridge/README.md) — record/replay typed traffic to MCAP.
- [`bridges/ros2_bridge/`](../ros2_bridge/README.md) — bidirectional bridge between SpatialDDS and ROS 2.
