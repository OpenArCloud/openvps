# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

# Cyclone DDS comes from the SpatialDDS demo's published base image rather than being
# rebuilt here. It is the same artefact the demo and its bridges run on, so the localizer
# cannot drift from them, and it saves compiling the C library on every image build.
#
# The base is Ubuntu 22.04 and this image is 24.04. Copying the install prefix across works
# because glibc is backward compatible: a binary linked against 22.04's 2.35 runs on 24.04's
# 2.39. The reverse would not, so this direction is load-bearing — do not "modernise" the
# base to a newer distro than the target. Verified on linux/amd64: ldd reports no missing
# objects, idlc runs, and a publish/subscribe round trip completes inside the 24.04 image.
FROM ghcr.io/openarcloud/cyclonedds-python-base:11.0.1-ubuntu22.04 AS ddsbase

FROM nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04 AS production

# Network proxy
ARG HTTP_PROXY
ARG HTTPS_PROXY
RUN echo "Acquire::http::proxy \"$HTTP_PROXY\";\nAcquire::https::proxy \"$HTTPS_PROXY\";" > /etc/apt/apt.conf
ENV http_proxy=$HTTP_PROXY
ENV https_proxy=$HTTPS_PROXY
RUN echo "http_proxy: ${HTTP_PROXY}"
RUN echo "https_proxy: ${HTTPS_PROXY}"

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

# Basic dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get upgrade -y && apt-get install -y \
    apt-utils \
    build-essential \
    cmake \
    curl \
    git \
    ninja-build \
    unzip \
    wget

# Dependecies of Colmap / hloc
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get install -y \
    libboost-program-options-dev \
    libboost-graph-dev \
    libboost-system-dev \
    libeigen3-dev \
    libflann-dev \
    libfreeimage-dev \
    libmetis-dev \
    libgoogle-glog-dev \
    libgtest-dev \
    libgmock-dev \
    libsqlite3-dev \
    libglew-dev \
    qtbase5-dev \
    libqt5opengl5-dev \
    libcgal-dev \
    libceres-dev \
    libeigen3-dev \
    libsuitesparse-dev

# Install Python devtools
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get install -y \
    python3-dev \
    python3-setuptools \
    python3-pip \
    python3-venv
# Create Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
# Activate the virtual environment permanently
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install OpenCV and other basic dependencies
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --upgrade --verbose \
    numpy pyyaml \
    opencv-python \
    opencv-contrib-python \
    transforms3d \
    setuptools

# Install hloc
COPY --from=hloc_context . /app/Hierarchical-Localization
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install packaging && \
    python3 -m pip install --no-build-isolation --verbose -e /app/Hierarchical-Localization

# Replace PyTorch with an earlier version if your GPU is not supported by the newest version
# If you see PyTorch UserWarning: CUDA initialization: The NVIDIA driver on your system is too old (found version xxxx).
# Please update your GPU driver ... Alternatively, ... install a PyTorch version that has been compiled with your version of the CUDA driver.
RUN pip uninstall torch -y
RUN pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1

# Replace pycolmap with an earlier version (see main README.md) that is compatible with the HLOC commit version
RUN pip install pycolmap==3.13

# Install FastAPI
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install "fastapi[standard]" pydantic-settings

# Cyclone DDS: C library, headers and tools from the base image above, then the Python
# binding into the venv. The binding builds a C extension against CYCLONEDDS_HOME, so the
# headers have to be present at install time even though only the libraries are needed at
# run time. 57 MB, against an image that is already several gigabytes.
#
# The version is pinned to match the base image exactly. The C library and the Python
# binding are released together and are not independently compatible; 0.10.5 in particular
# cannot load the generated 1.7 bindings at all, because its idlc emits the spec's `global`
# and `from` field names verbatim and they are Python keywords.
COPY --from=ddsbase /usr/local /usr/local
ENV CYCLONEDDS_HOME=/usr/local
ENV LD_LIBRARY_PATH=/usr/local/lib
RUN ldconfig
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install cyclonedds==11.0.1

# Fail the build rather than the deployment if the runtime did not survive the copy.
RUN python3 -c "import cyclonedds; from cyclonedds.domain import DomainParticipant; DomainParticipant(0); print('cyclonedds OK')"

COPY . .

RUN echo "appName=OpenVPS-MapLocalizer" >> server/.env
RUN echo "uploadsDir=/uploads" >> server/.env
RUN echo "debug=False" >> server/.env
RUN echo "maxLoadedMaps=8" >> server/.env
RUN echo "workerId=docker" >> server/.env

# default FastAPI port
EXPOSE 8000
# RTPS discovery and user traffic. Only reachable when the container is on the host network
# or these are published; a bridged container advertises an address no off-host peer can
# route to, which is why the AWS override runs this service with host networking.
EXPOSE 7400-7500/udp

CMD ["python3", "-m", "fastapi", "run", "server/main.py", "--proxy-headers"]
