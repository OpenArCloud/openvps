# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

# This file is part of OpenVPS: Open Visual Positioning Service
# Author: Gabor Soros (gabor.soros@nokia-bell-labs.com)

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS production

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
    python3-pip \
    python3-venv \
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

# Create Python virtual environment
#RUN python3 -m pip install --upgrade pip
#RUN python3 -m venv .venv
#RUN . .venv/bin/activate

# Install OpenCV and other basic dependencies
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --upgrade --verbose \
    numpy pyyaml \
    opencv-python \
    opencv-contrib-python \
    transforms3d \
    setuptools

# Install hloc
COPY --from=hloc_context . /app/hloc
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --no-build-isolation --verbose -e /app/hloc

# Install FastAPI
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install "fastapi[standard]" pydantic-settings

COPY . .

RUN echo "appName=OpenVPS-MapLocalizer" >> server/.env
RUN echo "uploadsDir=/uploads" >> server/.env
RUN echo "debug=False" >> server/.env

# default FastAPI port
EXPOSE 8000

CMD ["python3", "-m", "fastapi", "run", "server/main.py", "--proxy-headers"]
