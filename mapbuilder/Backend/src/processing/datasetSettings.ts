/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {StageSettingsSchema} from "./stageSettings";

export const DatasetSettingsSchema: StageSettingsSchema = {
    stageName: "datasetSettings",
    title: "Dataset",
    scope: "dataset",
    settings: [
        {
            kind: "enum",
            key: "thumbnailRotation",
            label: "Thumbnail rotation degrees (counter-clockwise)",
            default: 0,
            options: [0, 90, 180, 270].map((value) => ({label: value.toString(), value})),
        },
    ],
};

export function getDatasetSettingsSchemas(): StageSettingsSchema[] {
    return [DatasetSettingsSchema];
}
