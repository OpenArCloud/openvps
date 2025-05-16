/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

// TODO: remove this file and move everything to tasks and datasets
// TODO: rename this GeoPose because it is different than the OGC GeoPose and this is confusing

import * as fs from "node:fs";
import {EnvironmentalConfig} from "./index";

export interface GeoPose {
    latitude: number;
    longitude: number;
    height: number;
    matrix: number[][];
}

const DEFAULT_TRANSFORM: GeoPose = {
    longitude: parseFloat(process.env.DEFAULT_LONGITUDE!),
    latitude: parseFloat(process.env.DEFAULT_LATITUDE!),
    height: parseFloat(process.env.DEFAULT_HEIGHT!),
    matrix: [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ],
};

export function saveHlocTransform(dataSetId: string, mapId: string, geoPose: GeoPose, config: EnvironmentalConfig) {
    const mapPath = `${config.uploadsDir}/${dataSetId}/hlocMaps/${mapId}/transform.json`;
    fs.writeFileSync(mapPath, JSON.stringify(geoPose, null, 2));
}

export function readHlocTransform(dataSetId: string, mapId: string, config: EnvironmentalConfig): GeoPose {
    const mapPath = `${config.uploadsDir}/${dataSetId}/hlocMaps/${mapId}/transform.json`;

    if (!fs.existsSync(mapPath)) {
        return DEFAULT_TRANSFORM;
    }

    try {
        const result = JSON.parse(fs.readFileSync(`${mapPath}`).toString());
        return result as GeoPose;
    } catch (error) {
        console.error(error);
        return DEFAULT_TRANSFORM;
    }
}
