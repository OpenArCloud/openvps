/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

let websocketUrl = `ws://localhost:3000`;
if (process.env.NODE_ENV === "production") {
    websocketUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
}

export const API_URLS = {
    GET_MAPS: "/maps",
    GET_SELECTED_MAP: "/maps/selected",
    UPLOAD_STRAY_RECORDING_ZIP: "/uploadStrayRecordingZip",
    HLOC_REGISTER_CONFIG: "/maps/:id/hloc/registerConfig",
    HLOC_START_PROCESSING: "/maps/:id/hloc/:mapId/process",
    HLOC_DOWNLOAD_MAP: "/maps/:id/hloc/:mapId/download",
    RENAME_MAP: "/maps/:id/rename",
    SELECT_MAP: "/maps/:id/select",
    DELETE_MAP: "/maps/:id",
    WEBSOCKET: websocketUrl,
    LOGIN: "/realms/mapBuilder/protocol/openid-connect/token",
    LOGOUT: "/realms/mapBuilder/protocol/openid-connect/logout",
    MAPALIGNER_URL: import.meta.env.VITE_MAPALIGNER_URL + "/?id=:id&type=:type",
};

export const AUTH_ENABLED: boolean = false;
export const AUTH_CLIENT_ID: string = "mb";
export const AUTH_CLIENT_SECRET: string = "0yNB4LhNsgBNpajLPPVa5Y30hyNpGQZ9";
