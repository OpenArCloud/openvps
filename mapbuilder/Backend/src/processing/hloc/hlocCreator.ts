/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {HlocCreationState, TaskDescription, TaskStatus, TaskStatusPublisher} from "../../dataSet";
import {UploadLocation} from "../../uploadLocation";
import {EnvironmentalConfig} from "../../index";
import {ScriptExecutor} from "../scriptexecutor";
import {stringify} from "yaml";
import fs from "fs-extra";
import path from "node:path";
import {HlocConfig} from "./hlocConfig";
import {HlocFormatStage, HlocImageFilterStage, HlocConfigurationStage, HlocMapBuildStage, HlocMapPlyExportStage, HlocMapZipExportStage} from "./hlocStages";
import {getHlocMapWorkDirectory} from "./hlocMapManager";

//export function writeHlocConfigToFile(hlocConfig: HlocConfig, uploadLocation: UploadLocation, mapId: string): string {
//    const configFileName = path.join(getHlocMapWorkDirectory(uploadLocation.getDataSetRoot(), mapId), "mapBuildConfig.yaml")
//
//    const hlocAsYaml = stringify(hlocConfig);
//    console.log(` [writeHlocConfigToFile] persisting config to file: ${hlocAsYaml}`)
//    fs.writeFileSync(configFileName, hlocAsYaml);
//
//    return configFileName;
//}

export class HlocCreator extends ScriptExecutor {
    constructor(
        private state: HlocCreationState,
        private uploadLocation: UploadLocation,
        private statusPublisher: TaskStatusPublisher<HlocCreationState>,
        private config: EnvironmentalConfig,
    ) {
        super(config.scriptsDir);
    }

    public subtaskPublishStatus = (task: TaskDescription) => {
        switch (task.type) {
            case HlocFormatStage.stageName:
                this.state.tasks.hlocFormat = task;
                break;
            case HlocImageFilterStage.stageName:
                this.state.tasks.hlocImageFilter = task;
                break;
            case HlocConfigurationStage.stageName:
                this.state.tasks.hlocConfiguration = task;
                break;
            case HlocMapBuildStage.stageName:
                this.state.tasks.hlocMapBuild = task;
                break;
            case HlocMapPlyExportStage.stageName:
                this.state.tasks.hlocMapPlyExport = task;
                break;
            case HlocMapZipExportStage.stageName:
                this.state.tasks.hlocMapZipExport = task;
                break;
            default:
                console.error("[hloc] Unknown processing stage: ", task.type);
                break;
        }

        if (Object.values(this.state.tasks).some((task) => task.status === TaskStatus.failed)) {
            this.state.status = TaskStatus.failed;
        }

        if (Object.values(this.state.tasks).every((task) => task.status === TaskStatus.completed)) {
            this.state.status = TaskStatus.completed;
        }

        this.statusPublisher(task, this.state);
    };

    async startProcessing(): Promise<HlocCreationState> {
        this.state.status = TaskStatus.active;

        const workDir = getHlocMapWorkDirectory(this.uploadLocation.getDataSetRoot(), this.state.mapId);
        if (!fs.existsSync(workDir)) {
            fs.mkdirSync(getHlocMapWorkDirectory(this.uploadLocation.getDataSetRoot(), this.state.mapId), {recursive: true});
        }

        if (this.state.tasks.hlocFormat.status != TaskStatus.completed) {
            const hlocFormatStatus = this.state.tasks.hlocFormat;
            const hlocFormatStage = new HlocFormatStage(this.uploadLocation, this.config, this.subtaskPublishStatus, hlocFormatStatus);
            const result = await hlocFormatStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        if (this.state.tasks.hlocImageFilter.status != TaskStatus.completed) {
            const hlocImageFilterStatus = this.state.tasks.hlocImageFilter;
            const hlocImageFilterStage = new HlocImageFilterStage(this.uploadLocation, this.state.mapId, this.config, this.subtaskPublishStatus, hlocImageFilterStatus);
            const result = await hlocImageFilterStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        if (this.state.tasks.hlocConfiguration.status != TaskStatus.completed) {
            const hlocConfigurationStatus = this.state.tasks.hlocConfiguration;
            const hlocConfigurationStage = new HlocConfigurationStage(workDir, this.state.mapId, this.config, this.subtaskPublishStatus, hlocConfigurationStatus);
            const result = await hlocConfigurationStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        if (this.state.tasks.hlocMapBuild.status != TaskStatus.completed) {
            const buildMapStatus = this.state.tasks.hlocMapBuild;
            const mapBuildStage = new HlocMapBuildStage(workDir, this.config, this.subtaskPublishStatus, buildMapStatus);
            const result = await mapBuildStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        if (this.state.tasks.hlocMapPlyExport.status != TaskStatus.completed) {
            const mapPlyExportStatus = this.state.tasks.hlocMapPlyExport;
            const mapPlyExportStage = new HlocMapPlyExportStage(workDir, this.config, this.subtaskPublishStatus, mapPlyExportStatus);
            const result = await mapPlyExportStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        if (this.state.tasks.hlocMapZipExport.status != TaskStatus.completed) {
            const mapZipExportStatus = this.state.tasks.hlocMapZipExport;
            const mapZipExportStage = new HlocMapZipExportStage(workDir, this.config, this.subtaskPublishStatus, mapZipExportStatus);
            const result = await mapZipExportStage.execute();
            if (result === TaskStatus.failed) {
                return this.state;
            }
        }

        this.state.status = TaskStatus.completed;
        return this.state;
    }

    public getMappingConfig(): HlocConfig {
        return this.state.mappingConfig;
    }

    public getCurrentStatus(): HlocCreationState {
        return this.state;
    }

    public getSparsePlyDownloadLink() {
        if (this.state.status === TaskStatus.completed) {
            const mapWorkDir = getHlocMapWorkDirectory(this.uploadLocation.getDataSetRoot(), this.state.mapId);
            const fileName = "sparse.ply";
            return path.join(mapWorkDir, fileName);
        } else {
            console.error("[hloc] Download link requested for unfinished map!");
        }
    }

    public getAllMapDataDownloadLink() {
        if (this.state.status === TaskStatus.completed) {
            const mapWorkDir = getHlocMapWorkDirectory(this.uploadLocation.getDataSetRoot(), this.state.mapId);
            const fileName = "hloc_reconstruction.zip";
            return path.join(mapWorkDir, fileName);
        } else {
            console.error("[hloc] Download link requested for unfinished map!");
        }
    }
}
