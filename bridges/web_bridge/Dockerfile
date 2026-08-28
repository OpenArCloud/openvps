# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
#
# SpatialDDS web bridge: carries SpatialDDS types to browser clients, which cannot speak
# RTPS. A transport adapter, not a protocol bridge — payloads are SpatialDDS on both sides,
# and nothing here translates to or from GeoPose Protocol.
#
# Unlike the localizer this FROMs the published base image directly: no GPU, so no CUDA
# base to reconcile with.
#
# Build context is the repository root, not this directory, because the vendored SpatialDDS
# packages are shared with the localizer and the demo's own module layout has to be
# preserved — bridges/web_bridge/__main__.py runs uvicorn against
# "bridges.web_bridge.server:app", so the package path has to survive into the image. Laying
# it out any other way would mean editing a vendored file.

FROM ghcr.io/openarcloud/cyclonedds-python-base:11.0.1-ubuntu22.04

WORKDIR /app

COPY bridges/web_bridge/requirements.txt ./
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Vendored from SpatialDDS-demo 6f29ecf — the same snapshot the localizer carries.
COPY maplocalizer/server/vendor/spatialdds_demo ./spatialdds_demo
COPY maplocalizer/server/vendor/spatialdds_idl ./spatialdds_idl
COPY maplocalizer/server/vendor/spatialdds_validation.py ./
# spatialdds_test.py is the demo's test harness and has no business in a service image. It
# is here because bridges/web_bridge/server.py imports MockSensorData from it, for a
# blob_ref helper that spatialdds_demo.blob already provides. Vendored unmodified rather
# than patched, per the standing rule not to fork the demo; reported instead.
COPY maplocalizer/server/vendor/spatialdds_test.py ./

COPY bridges/__init__.py ./bridges/__init__.py
COPY bridges/web_bridge ./bridges/web_bridge

# Configuration comes from the deployment; the image carries none of its own.
#   SPATIALDDS_TRANSPORT=dds
#   CYCLONEDDS_URI=file:///etc/cyclonedds.xml
#   SPATIALDDS_DDS_DOMAIN / SPATIALDDS_BOOTSTRAP_DOMAIN   (must agree — see below)
#   SPATIALDDS_BRIDGE_ALLOW_PUBLISH=1
#
# Those two domain variables are separate and default differently. The bridge serves
# /.well-known/spatialdds/bootstrap from SPATIALDDS_BOOTSTRAP_*, which defaults to domain 1,
# while the bus it joins comes from SPATIALDDS_DDS_DOMAIN. Set only the latter and the
# deployment advertises a domain it does not publish on: a client following this service's
# own bootstrap joins an empty domain and sees nothing, with no error on either side. The
# demo shipped exactly that and fixed it in eb20877.

RUN useradd -m -u 1001 bridge && chown -R bridge:bridge /app
USER bridge

EXPOSE 8088
EXPOSE 7400-7500/udp

CMD ["python3", "-m", "bridges.web_bridge"]
