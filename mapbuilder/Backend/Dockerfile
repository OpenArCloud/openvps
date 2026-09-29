# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

#FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04 AS production
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


# nodejs
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    curl -sL https://deb.nodesource.com/setup_22.x | bash -
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get install -y nodejs

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

# basic python dependencies
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --upgrade --verbose \
    numpy pyyaml ruamel.yaml \
    matplotlib \
    opencv-python \
    opencv-contrib-python \
    transforms3d \
    setuptools

# Install hloc
COPY --from=hloc_context . /app/Hierarchical-Localization
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --no-build-isolation --verbose -e /app/Hierarchical-Localization
# Install additional dependencies of r2d2 and dir submodules of hloc
RUN --mount=type=cache,target=/root/.cache/pip python3 -m pip install --verbose \
    pillow \
    scikit-learn

# Replace PyTorch with an earlier version if your GPU is not supported by the newest version
# If you see PyTorch UserWarning: CUDA initialization: The NVIDIA driver on your system is too old (found version xxxx).
# Please update your GPU driver ... Alternatively, ... install a PyTorch version that has been compiled with your version of the CUDA driver.
RUN pip uninstall torch -y
RUN pip install torch==2.4.1 torchvision==0.19.1 torchaudio==2.4.1

# Replace pycolmap with an earlier version (see main README.md) that is compatible with the HLOC commit version
RUN pip install pycolmap==3.13

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
RUN echo "hlocDir=/app/Hierarchical-Localization" >> .env
RUN echo "shell=bash" >> .env
RUN mkdir -p /uploads

EXPOSE 3000

# Match host UID/GID for bind-mounted volumes. Ubuntu/CUDA images often already
# define GID 1000 (e.g. group "ubuntu") and UID 1000, so blind groupadd/useradd fails.
ARG GROUP_ID=1000
ARG USER_ID=1000
RUN set -eux; \
    if getent group "${GROUP_ID}" >/dev/null; then \
      GRP_NAME="$(getent group "${GROUP_ID}" | cut -d: -f1)"; \
    else \
      groupadd -r -g "${GROUP_ID}" openvps; \
      GRP_NAME=openvps; \
    fi; \
    if getent passwd "${USER_ID}" >/dev/null; then \
      echo "UID ${USER_ID} already present ($(getent passwd "${USER_ID}" | cut -d: -f1)), reusing for runtime USER"; \
    else \
      useradd --no-log-init -r -m -g "${GRP_NAME}" -u "${USER_ID}" mapbuilder; \
    fi

# Numeric user:group so runtime matches build args even when the base image already
# had that UID/GID under a different account name (e.g. ubuntu).
USER ${USER_ID}:${GROUP_ID}

CMD ["node", "dist/index.js"]
