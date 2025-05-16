/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {UploadLocation} from "../../uploadLocation";
import {EnvironmentalConfig} from "../../index";
import {HlocCreationState, TaskStatus, TaskStatusPublisher} from "../../dataSet";
import {HlocConfig} from "./hlocConfig";
import _ from "lodash";
import {HlocCreator} from "./hlocCreator";
import {v4 as uuidv4} from "uuid";
import path from "node:path";
import {HlocFormatStage, HlocImageFilterStage, HlocConfigurationStage, HlocMapBuildStage, HlocMapPlyExportStage, HlocMapZipExportStage} from "./hlocStages";

export function getHlocMapWorkDirectory(mapUploadRoot: string, hlocMapId: string) {
    return path.join(mapUploadRoot, "hlocMaps", hlocMapId);
}

//export function getHlocStatusFileName(mapUploadRoot: string, hlocMapId: string) {
//    return path.join(mapUploadRoot, 'hlocMaps', hlocMapId, 'status.json');
//}

export class HlocMapManager {
    private hlocMaps: Map<string, HlocCreator> = new Map<string, HlocCreator>();

    constructor(
        private uploadLocation: UploadLocation,
        private hlocStatusUpdate: TaskStatusPublisher<HlocCreationState>,
        private config: EnvironmentalConfig,
    ) {}

    public addMap(hlocState: HlocCreationState) {
        this.hlocMaps.set(hlocState.mapId, new HlocCreator(hlocState, this.uploadLocation, this.hlocStatusUpdate, this.config));
    }

    public addMaps(hlocState: HlocCreationState[]) {
        for (const status of hlocState) {
            this.addMap(status);
        }
    }

    async processItemWithMapId(mapId: string): Promise<HlocCreationState> {
        const creator = this.hlocMaps.get(mapId);
        if (creator) {
            const status = await creator.startProcessing();
            return status;
        } else {
            console.log(` [resumeProcessingPresentItem] Error: mapId ${mapId} not present`);
            return {
                mapId: mapId,
                mappingConfig: {},
                status: TaskStatus.failed,
                tasks: {
                    hlocFormat: {
                        type: "hlocFormat",
                        status: TaskStatus.failed,
                    },
                    hlocImageFilter: {
                        type: "hlocImageFilter",
                        status: TaskStatus.failed,
                    },
                    hlocConfiguration: {
                        type: "hlocConfiguration",
                        status: TaskStatus.failed,
                    },
                    hlocMapBuild: {
                        type: "hlocMapBuild",
                        status: TaskStatus.failed,
                    },
                    hlocMapPlyExport: {
                        type: "hlocMapPlyExport",
                        status: TaskStatus.failed,
                    },
                    hlocMapZipExport: {
                        type: "hlocMapZipExport",
                        status: TaskStatus.failed,
                    },
                },
            };
        }
    }

    public registerNewConfig(hlocConfig: HlocConfig): HlocCreationState {
        const presentMapIdProcessor = this.checkIfConfigAlreadyPresent(hlocConfig);
        if (presentMapIdProcessor) {
            return presentMapIdProcessor.getCurrentStatus();
        }

        const hlocMapId = uuidv4().toString();

        const hlocState: HlocCreationState = {
            mapId: hlocMapId,
            mappingConfig: hlocConfig,
            status: TaskStatus.active,
            tasks: {
                hlocFormat: {
                    type: HlocFormatStage.stageName,
                    status: TaskStatus.notStarted,
                },
                hlocImageFilter: {
                    type: HlocImageFilterStage.stageName,
                    status: TaskStatus.notStarted,
                },
                hlocConfiguration: {
                    type: HlocConfigurationStage.stageName,
                    status: TaskStatus.notStarted,
                },
                hlocMapBuild: {
                    type: HlocMapBuildStage.stageName,
                    status: TaskStatus.notStarted,
                },
                hlocMapPlyExport: {
                    type: HlocMapPlyExportStage.stageName,
                    status: TaskStatus.notStarted,
                },
                hlocMapZipExport: {
                    type: HlocMapZipExportStage.stageName,
                    status: TaskStatus.notStarted,
                },
            },
        };

        const creator = new HlocCreator(hlocState, this.uploadLocation, this.hlocStatusUpdate, this.config);
        this.hlocMaps.set(hlocMapId, creator);

        return hlocState;
    }

    public getStatusOfMap(mapId: string): HlocCreationState | undefined {
        const mapCreator = this.hlocMaps.get(mapId);
        if (mapCreator) {
            return mapCreator.getCurrentStatus();
        }
    }

    public getStatusOfAllMaps(): HlocCreationState[] {
        const allStates: HlocCreationState[] = Array.from(this.hlocMaps.values()).map((hloc) => hloc.getCurrentStatus());
        return allStates;
    }

    private checkIfConfigAlreadyPresent(hlocConfig: HlocConfig): HlocCreator | undefined {
        for (const value of this.hlocMaps.values()) {
            if (_.isEqual(value.getMappingConfig(), hlocConfig)) {
                return value;
            }
        }
    }

    public getSparsePlyDownloadLink(hlocMapId: string) {
        const mapProcessor = this.hlocMaps.get(hlocMapId);
        if (mapProcessor) {
            return mapProcessor.getSparsePlyDownloadLink();
        } else {
            console.error(`Map ${hlocMapId} not found`);
        }
    }

    public getAllMapDataDownloadLink(hlocMapId: string) {
        const mapProcessor = this.hlocMaps.get(hlocMapId);
        if (mapProcessor) {
            return mapProcessor.getAllMapDataDownloadLink();
        }
        console.error(`Map ${hlocMapId} not found`);
    }
}
