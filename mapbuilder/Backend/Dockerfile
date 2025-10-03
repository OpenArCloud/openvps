# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
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

# nodejs
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    curl -sL https://deb.nodesource.com/setup_22.x | bash -
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get install -y nodejs

# basic python dependencies
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --upgrade --verbose \
    numpy pyyaml ruamel.yaml \
    matplotlib \
    opencv-python \
    opencv-contrib-python \
    transforms3d \
    setuptools

# Install hloc
COPY --from=hloc_context . /app/hloc
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --no-build-isolation --verbose -e /app/hloc

# Replace PyTorch with an earlier version if your GPU is not supported by the newest version
#RUN pip uninstall torch -y
#RUN pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1

# Install scripts
COPY --from=scripts_context . /app/scripts

# Install Backend
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run buildnolint

# Create env file
RUN echo "uploadsDir=/uploads" >> .env
RUN echo "scriptsDir=/app/scripts" >> .env
RUN echo "hlocDir=/app/hloc" >> .env
RUN echo "shell=bash" >> .env
RUN mkdir -p /uploads

EXPOSE 3000

ARG GROUP_ID
ARG USER_ID
RUN groupadd -r -g ${GROUP_ID} openvps && useradd --no-log-init -r -m -g openvps -u ${USER_ID} mapbuilder
USER mapbuilder

CMD ["node", "dist/index.js"]
