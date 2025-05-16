/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {IdempotentStage} from "./stage";
import {UploadLocation} from "../uploadLocation";
import {EnvironmentalConfig} from "../index";
import {StageUpdatePublisher, TaskDescription, TaskStatus} from "../dataSet";

export class ExtractTask extends IdempotentStage {
    constructor(
        private uploadLocation: UploadLocation,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(ExtractTask.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "datasetExtract";

    async scriptProcessing() {
        const extractCommand = `python3 stray_zip_extract.py \
            --zip_path ${this.uploadLocation.getZipFilePath()} \
            --output_dir ${this.uploadLocation.getStrayRecordingDir()}`;
        await this.executeCommand(extractCommand, this.config.shell);
    }

    public static getDefaultDescription(): TaskDescription {
        return {
            type: ExtractTask.stageName,
            status: TaskStatus.notStarted,
        };
    }
}
