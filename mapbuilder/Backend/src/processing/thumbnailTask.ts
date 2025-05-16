/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {IdempotentStage} from "./stage";
import {UploadLocation} from "../uploadLocation";
import {EnvironmentalConfig} from "../index";
import {StageUpdatePublisher, TaskDescription, TaskStatus} from "../dataSet";

export class ThumbnailTask extends IdempotentStage {
    constructor(
        private uploadLocation: UploadLocation,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(ThumbnailTask.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "datasetThumbnail";

    async scriptProcessing() {
        const extractCommand = `python3 generate_thumbnail.py \
            --input_path ${this.uploadLocation.getStrayRecordingDir()}/rgb.mp4 \
            --output_path ${this.uploadLocation.getThumbnailFilePath()} \
            --rotate_degrees 90`;
        await this.executeCommand(extractCommand, this.config.shell);
    }

    public static getDefaultDescription(): TaskDescription {
        return {
            type: ThumbnailTask.stageName,
            status: TaskStatus.notStarted,
        };
    }
}
