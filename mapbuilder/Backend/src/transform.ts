/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

// TODO: remove this file and move everything to tasks and datasets

import * as fs from "node:fs";
import {EnvironmentalConfig} from "./index";

/**
 * Map / world alignment in ``hlocMaps/<mapId>/transform.json`` (not OGC GeoPose).
 * Use ``null`` geodetic fields when the map has no global geo anchor (scale / ENU frame only).
 */
export interface WorldAlignmentInfo {
    latitude?: number | null;
    longitude?: number | null;
    height?: number | null;
    matrix: number[][];
}

const kDefaultWorldAlignmentInfo: WorldAlignmentInfo = {
    longitude: null,
    latitude: null,
    height: null,
    matrix: [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ],
};

function numOrNull(v: unknown): number | null {
    if (v === null || v === undefined) {
        return null;
    }
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

export function saveHlocTransform(
    dataSetId: string,
    mapId: string,
    body: Partial<WorldAlignmentInfo> & {matrix: number[][]},
    config: EnvironmentalConfig,
) {
    const mapPath = `${config.uploadsDir}/${dataSetId}/hlocMaps/${mapId}/transform.json`;
    const payload: WorldAlignmentInfo = {
        latitude: numOrNull(body.latitude),
        longitude: numOrNull(body.longitude),
        height: numOrNull(body.height),
        matrix: body.matrix,
    };
    fs.writeFileSync(mapPath, JSON.stringify(payload, null, 2));
}

export function readHlocTransform(
    dataSetId: string,
    mapId: string,
    config: EnvironmentalConfig,
): WorldAlignmentInfo {
    const mapPath = `${config.uploadsDir}/${dataSetId}/hlocMaps/${mapId}/transform.json`;

    if (!fs.existsSync(mapPath)) {
        return kDefaultWorldAlignmentInfo;
    }

    try {
        const result = JSON.parse(fs.readFileSync(`${mapPath}`).toString()) as Record<string, unknown>;
        return {
            latitude: numOrNull(result.latitude),
            longitude: numOrNull(result.longitude),
            height: numOrNull(result.height),
            matrix: (result.matrix as number[][]) ?? kDefaultWorldAlignmentInfo.matrix,
        };
    } catch (error) {
        console.error(error);
        return kDefaultWorldAlignmentInfo;
    }
}
