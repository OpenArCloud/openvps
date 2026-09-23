/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {UploadLocation} from "./uploadLocation";
import {EnvironmentalConfig} from "./index";
import {Server} from "socket.io";
import {GenericStatusPublisher} from "./statusPublisher";
import {ExtractTask} from "./processing/extractTask";
import {ThumbnailTask} from "./processing/thumbnailTask";
import {HlocMapManager} from "./processing/hloc/hlocMapManager";
import {DatasetSettingsSchema} from "./processing/datasetSettings";
import {PipelineStageSettings, resolveStageSettings} from "./processing/stageSettings";

import fs from "node:fs";

export enum TaskStatus {
    notStarted = "Not started",
    active = "Active",
    completed = "Completed",
    failed = "Failed",
}

export type FrontendStatusUpdate = TaskDescription & ProcessMetadata;

export interface TaskDescription {
    type: string;
    startTime?: number;
    runTime?: number;
    status: TaskStatus;
}

export interface ProcessMetadata {
    id: string;
    zip: string;
    name: string;
    size: number;
    datasetSettings?: PipelineStageSettings;
}

export interface HlocCreationState {
    status: TaskStatus;
    mapId: string;
    stageSettings: PipelineStageSettings;
    mappingConfig?: unknown;
    tasks: HlocStages;
}

export interface HlocStages {
    hlocFormat: TaskDescription;
    hlocImageFilter: TaskDescription;
    hlocConfiguration: TaskDescription;
    hlocMapBuild: TaskDescription;
    hlocMapScaleEstimation: TaskDescription;
    hlocMapPlyExport: TaskDescription;
    hlocMapZipExport: TaskDescription;
}

export interface DataSetStatus {
    metadata: ProcessMetadata;
    datasetUpload: TaskDescription;
    datasetExtract: TaskDescription;
    datasetThumbnail: TaskDescription;
    hloc?: HlocCreationState[];
}

export type StageUpdatePublisher = (task: TaskDescription) => void;

export type TaskStatusPublisher<PipelineStatus> = (task: TaskDescription, state: PipelineStatus) => void;

// TODO: can be removed?
//export function getStatusFileName(uploadRoot: string): string {
//    return path.join(uploadRoot, "status.json");
//}

export class DataSet {
    static readonly uploadTaskName = "datasetUpload";
    static readonly strayRecordingSubdir = "/stray_recording";

    private mapStatusPublisher: GenericStatusPublisher<DataSetStatus>;

    private hlocMapManager: HlocMapManager;

    constructor(private state: DataSetStatus, private uploadLocation: UploadLocation, private readonly io: Server, private config: EnvironmentalConfig) {
        this.mapStatusPublisher = new GenericStatusPublisher<DataSetStatus>(this.io, uploadLocation.getStatusFilePath(), this.state.metadata);

        this.hlocMapManager = new HlocMapManager(uploadLocation, this.hlocStatusUpdate, config);
        if (state.hloc) {
            const hlocConfigs = Array.from(state.hloc.values());
            this.hlocMapManager.addMaps(hlocConfigs);
        }
    }

    public hlocStatusUpdate = (task: TaskDescription, hlocState: HlocCreationState) => {
        const mapId = hlocState.mapId;
        const statusOfMap = this.hlocMapManager.getStatusOfMap(mapId);

        if (statusOfMap) {
            this.overwriteHlocStatus(statusOfMap);
        }

        this.mapStatusPublisher.publishStatus(task, this.state, {mapId});
    };

    private overwriteHlocStatus(hlocStatus: HlocCreationState) {
        if (!this.state.hloc) {
            this.state.hloc = [];
        }

        this.state.hloc = this.state.hloc.filter((status) => status.mapId != hlocStatus.mapId);
        this.state.hloc.push(hlocStatus);
    }

    public registerHlocConfig(stageSettings: PipelineStageSettings) {
        if (!this.state.hloc) {
            this.state.hloc = [];
        }

        const result = this.hlocMapManager.registerNewConfig(stageSettings);
        this.overwriteHlocStatus(result);

        return result;
    }

    public async startHlocProcessing(hlocMapId: string): Promise<TaskStatus> {
        if (!this.state.hloc) {
            this.state.hloc = [];
        }

        const result = await this.hlocMapManager.processItemWithMapId(hlocMapId);
        this.overwriteHlocStatus(result);
        return result.status;
    }

    public async runExtractStage() {
        const publishExtractTaskStatus = (task: TaskDescription) => {
            this.state[ExtractTask.stageName] = task;
            this.mapStatusPublisher.publishStatus(task, this.state);
        };
        const extractTask = new ExtractTask(this.uploadLocation, this.config, publishExtractTaskStatus, undefined);
        await extractTask.execute();
    }

    public async runThumbnailStage() {
        const publishThumbnailTaskStatus = (task: TaskDescription) => {
            this.state[ThumbnailTask.stageName] = task;
            this.mapStatusPublisher.publishStatus(task, this.state);
        };
        const datasetSettings = resolveStageSettings(DatasetSettingsSchema, this.uploadLocation.getDatasetSettings()?.[DatasetSettingsSchema.stageName]);
        const thumbnailTask = new ThumbnailTask(this.uploadLocation, datasetSettings.thumbnailRotation as number, this.config, publishThumbnailTaskStatus, undefined);
        await thumbnailTask.execute();
    }

    public rename(newName: string) {
        this.state.metadata.name = newName;
        this.mapStatusPublisher.publishMetadata(this.state);
    }

    public getThumbnailFilePath() {
        return this.uploadLocation.getThumbnailFilePath();
    }

    public deleteFiles() {
        fs.rmSync(this.uploadLocation.getDataSetRoot(), {recursive: true});
    }

    public getCurrentStatus(): DataSetStatus {
        return this.state;
    }

    public getHlocSparsePlyDownloadLink(mapId: string) {
        return this.hlocMapManager.getSparsePlyDownloadLink(mapId);
    }

    public getHlocZipDownloadLink(mapId: string) {
        return this.hlocMapManager.getAllMapDataDownloadLink(mapId);
    }
}
