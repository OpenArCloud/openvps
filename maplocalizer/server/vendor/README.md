# Vendored SpatialDDS code

Copied from `OpenArCloud/SpatialDDS-demo` at **`6f29ecf`** ("web: discover the VPS by
geohash, and a REST window beside the DDS one"). Do not edit these files here — the demo is
the upstream. To take a newer version, re-copy and record the commit above.

The whole `spatialdds_demo` package is vendored, not a chosen subset. Cherry-picking
modules was tried first and was a mistake: the package's internal imports and the bridge's
own imports between them reach most of it, and each missing module surfaced only as an
ImportError one build later.

| Path | Why it is here |
|---|---|
| `spatialdds_idl/` | Generated Python bindings for the SpatialDDS 1.7 IDL (`idlc -l py`). Checked in upstream, so neither `idlc` nor Docker is needed to build. |
| `spatialdds_demo/` | The demo's runtime package: QoS profiles, typed transport, blob chunking, JSON mapping, discovery over bus and HTTP, the topic registry, service and client loops. |
| `spatialdds_validation.py` | Coverage and manifest validation. Imported by `discovery_http`. |
| `spatialdds_test.py` | **Test harness, and it should not be needed.** `bridges/web_bridge/server.py` imports `MockSensorData` from it for a `blob_ref` helper that `spatialdds_demo.blob.blob_ref` already provides. Vendored unmodified rather than patched, per the rule against forking the demo. Reported upstream. |

Two of the QoS details are load-bearing and easy to undo by accident. Deadline is a
request/offered policy, so a reader asking 33 ms does not match a writer offering none and
the failure is silent. History is reader-side, which is why `make_reader(keep_all=True)`
exists for reply topics whose type has no `@key`.

## Why vendored rather than a dependency

The demo is not published as a package, and the standing brief for this work says to vendor
or pin rather than edit it in place. Pinning by git submodule was considered and rejected:
the localizer image is built from the `maplocalizer` Compose context, which cannot see paths
outside it, so a submodule at the repository root would need an `additional_contexts` entry
in the upstream Compose file — a change to a file this branch deliberately leaves alone.

The web bridge carries its own copy for the same reason: it is a separate build context.
Two snapshots of the same commit is the cost of keeping each image self-contained and the
upstream Compose file untouched.
