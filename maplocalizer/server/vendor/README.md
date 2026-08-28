# Vendored SpatialDDS code

Copied from `OpenArCloud/SpatialDDS-demo` at **`6f29ecf`** ("web: discover the VPS by
geohash, and a REST window beside the DDS one"). Do not edit these files here — the demo is
the upstream. To take a newer version, re-copy and record the commit above.

| Path | Why it is here |
|---|---|
| `spatialdds_idl/` | Generated Python bindings for the SpatialDDS 1.7 IDL (`idlc -l py`). Checked in upstream, so neither `idlc` nor Docker is needed to build. |
| `spatialdds_demo/qos_profiles.py` | The §3.3.3 QoS table as CycloneDDS `Qos`. Deadline is request/offered, so a reader asking 33 ms will not match a writer offering none — silently. |
| `spatialdds_demo/typed_transport.py` | Topic cache, reader/writer factories, dispose. CycloneDDS rejects a second `Topic` for one name, hence the cache. |
| `spatialdds_demo/blob.py` | `BlobChunk` chunking and reassembly at the 65,535-byte binding ceiling, with CRC32 per chunk. |
| `spatialdds_demo/json_mapping.py` | dict ↔ typed conversion, including union handling that refuses an unknown case name. |
| `spatialdds_demo/discovery_bus.py` | Keyed `Announce` publish/subscribe with dispose-on-depart. |
| `spatialdds_demo/topics.py`, `topic_types.py` | Well-known topic names and the §3.3.2 registry, with the validator both sides share. |
| `spatialdds_demo/payloads.py`, `service_bus.py` | Payload builders and the VPS/coverage service and client loops. |

## Why vendored rather than a dependency

The demo is not published as a package, and the standing brief for this work says to vendor
or pin rather than edit it in place. Pinning by git submodule was considered and rejected:
the localizer image is built from the `maplocalizer` Compose context, which cannot see paths
outside it, so a submodule at the repository root would need an `additional_contexts` entry
in the upstream Compose file — a change to a file this branch deliberately leaves alone.

The web bridge carries its own copy for the same reason: it is a separate build context.
Two snapshots of the same commit is the cost of keeping each image self-contained and the
upstream Compose file untouched.
