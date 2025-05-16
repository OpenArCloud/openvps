/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {Server} from "socket.io";

import {persistStatus, publishStatusToFrontend} from "./statusPublisher";
import {UploadLocation} from "./uploadLocation";
import {EnvironmentalConfig} from "./index";
import {DataSetStatus, DataSet} from "./dataSet";
import {HlocConfig} from "./processing/hloc/hlocConfig";

export class TaskManager {
    private dataSets = new Map<string, DataSet>();

    constructor(
        private config: EnvironmentalConfig,
        private io: Server,
    ) {}

    public add(status: DataSetStatus) {
        const uploadLocation = new UploadLocation(this.config.uploadsDir, status.metadata);

        publishStatusToFrontend(status.metadata, status[DataSet.uploadTaskName], this.io);
        persistStatus(uploadLocation.getStatusFilePath(), status);

        const dataSet = new DataSet(status, uploadLocation, this.io, this.config);

        if (dataSet) {
            this.dataSets.set(status.metadata.id, dataSet);
        }
    }

    public addMultiple(statuses: DataSetStatus[]) {
        for (const status of statuses) {
            this.add(status);
        }
    }

    public delete(id: string): boolean {
        try {
            const dataSet = this.dataSets.get(id);
            if (!dataSet) {
                console.error("No dataset with id ", id);
                return false;
            }
            dataSet.deleteFiles();
            this.dataSets.delete(id);
            return true;
        } catch (error) {
            console.error(error);
            return false;
        }
    }

    public getStatusOfProcess(id: string): DataSetStatus | undefined {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            return dataSet.getCurrentStatus();
        }
    }

    public getAllStatuses(): DataSetStatus[] {
        const statuses: DataSetStatus[] = Array.from(this.dataSets.entries()).map(([id, taskProcessor]) => {
            console.log(` [service] Retrieving status of ${id}`);
            return taskProcessor.getCurrentStatus();
        });

        return statuses;
    }

    public getThumbnailFilePath(id: string): string | undefined {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            return dataSet.getThumbnailFilePath();
        }
    }

    public rename(id: string, newName: string): DataSetStatus | undefined {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            dataSet.rename(newName);
            return dataSet.getCurrentStatus();
        }
    }

    public async startExtractTask(id: string): Promise<DataSetStatus | undefined> {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            await dataSet.runExtractStage();
            return dataSet.getCurrentStatus();
        }
    }

    public async startThumbnailTask(id: string): Promise<DataSetStatus | undefined> {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            await dataSet.runThumbnailStage();
            return dataSet.getCurrentStatus();
        }
    }

    public registerHlocConfig(id: string, hlocConfig: HlocConfig) {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            return dataSet.registerHlocConfig(hlocConfig);
        }
    }

    public startHlocProcessing(id: string, hlocMapId: string) {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            dataSet.startHlocProcessing(hlocMapId);
            return dataSet.getCurrentStatus();
        }
    }

    public getHlocSparsePlyDownloadLink(id: string, mapId: string): string | undefined {
        const dataSet = this.dataSets.get(id);
        if (dataSet) {
            return dataSet.getHlocSparsePlyDownloadLink(mapId);
        } else {
            console.error("[hloc] No dataset for", id, mapId);
        }
    }
}
