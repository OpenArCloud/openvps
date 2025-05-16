# Copyright 2025 Nokia
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json ./
COPY package-lock.json ./
RUN npm ci
COPY . ./

ARG MAPALIGNER_URL
ENV VITE_MAPALIGNER_URL=${MAPALIGNER_URL}

RUN npm run build


FROM nginx:1.27-alpine

COPY --from=build /app/dist /app
COPY ./nginx.conf /etc/nginx/conf.d/default.conf
