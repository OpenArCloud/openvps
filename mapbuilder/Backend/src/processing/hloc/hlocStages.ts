/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {IdempotentStage} from "../stage";
import {UploadLocation} from "../../uploadLocation";
import {EnvironmentalConfig} from "../../index";
import {StageUpdatePublisher, TaskDescription} from "../../dataSet";
import {getHlocMapWorkDirectory} from "./hlocMapManager";
import {PipelineStageSettings, StageSettingsSchema, StageSettingsValues} from "../stageSettings";

export interface HlocStageClass {
    stageName: string;
    settingsSchema: StageSettingsSchema;
}

export interface HlocFormatSettings extends StageSettingsValues {
    resizeFactor: number;
    rotateDegrees: number;
}

export interface HlocConfigurationSettings extends StageSettingsValues {
    featureConf: string;
    matcherConf: string;
    retrievalConf: string;
    pairsStrategy: string;
}

export interface HlocMapScaleEstimationSettings extends StageSettingsValues {
    mode: string;
    minSharedImages: number;
    minPairDistanceM: number;
}

export class HlocFormatStage extends IdempotentStage {
    // This stage takes a StrayScanner recording and converts it to Colmap model format

    constructor(
        private uploadLocation: UploadLocation,
        private settings: HlocFormatSettings,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocFormatStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocFormat";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocFormatStage.stageName,
        title: "Formatting",
        scope: "run",
        settings: [
            {kind: "number", key: "resizeFactor", label: "Resize factor", default: 0.5, min: 0.01, max: 1, step: 0.01},
            {
                kind: "enum",
                key: "rotateDegrees",
                label: "Rotate degrees (counter-clockwise)",
                default: 0,
                options: [0, 90, 180, 270].map((value) => ({label: value.toString(), value})),
            },
        ],
    };

    async scriptProcessing() {
        const datasetStrayRecordingDir = this.uploadLocation.getStrayRecordingDir();
        const datasetStrayColmapFullDir = this.uploadLocation.getStrayColmapDir();
        const formatCommand = `python3 stray_to_colmap.py \
            --input_dir ${datasetStrayRecordingDir} \
            --output_dir ${datasetStrayColmapFullDir} \
            --resize_factor ${this.settings.resizeFactor} \
            --rotate_degrees ${this.settings.rotateDegrees} \
            --read_write_model_script_path ${this.config.hlocDir}/hloc/utils`; // WARNING: assuming path to read_write_model.py
        await this.executeCommand(formatCommand, this.config.shell);
    }
}

export class HlocImageFilterStage extends IdempotentStage {
    // This stage takes a Colmap model (including images) and filters the images based on certain criteria,
    // for example drops images that are too close to others

    constructor(
        private uploadLocation: UploadLocation,
        private hlocMapId: string,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocImageFilterStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocImageFilter";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocImageFilterStage.stageName,
        title: "Image filtering",
        scope: "run",
        settings: [],
    };

    async scriptProcessing() {
        const datasetStrayColmapFullDir = this.uploadLocation.getStrayColmapDir();
        const datasetStrayColmapFilteredDir = getHlocMapWorkDirectory(this.uploadLocation.getDataSetRoot(), this.hlocMapId) + "/prior_model";
        const processingCommand = `python3 colmap_model_filter_images.py  \
            --input_colmap_model_dir ${datasetStrayColmapFullDir} \
            --input_images_dir ${datasetStrayColmapFullDir}/images \
            --output_colmap_model_dir ${datasetStrayColmapFilteredDir} \
            --output_images_dir ${datasetStrayColmapFilteredDir}/images \
            --read_write_model_script_path ${this.config.hlocDir}/hloc/utils`; // WARNING: assuming path to read_write_model.py`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export class HlocConfigurationStage extends IdempotentStage {
    constructor(
        private hlocMapWorkDirectory: string,
        private settings: HlocConfigurationSettings,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocConfigurationStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocConfiguration";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocConfigurationStage.stageName,
        title: "Map build configuration",
        scope: "run",
        settings: [
            {
                kind: "enum",
                key: "featureConf",
                label: "Feature configuration",
                default: "superpoint_aachen",
                advanced: true,
                options: ["superpoint_aachen", "disk", "aliked-n16", "sift"].map((value) => ({label: value, value})),
            },
            {
                kind: "enum",
                key: "matcherConf",
                label: "Matcher configuration",
                default: "superglue",
                advanced: true,
                options: ["superglue", "disk+lightglue", "aliked+lightglue", "NN-superpoint", "NN-ratio"].map((value) => ({label: value, value})),
            },
            {
                kind: "enum",
                key: "retrievalConf",
                label: "Retrieval configuration",
                default: "netvlad",
                advanced: true,
                options: ["netvlad", "dir"].map((value) => ({label: value, value})),
            },
            {
                kind: "enum",
                key: "pairsStrategy",
                label: "Pairs strategy",
                default: "from_retrieval",
                advanced: true,
                options: ["from_exhaustive", "from_retrieval", "from_poses"].map((value) => ({label: value, value})),
            },
        ],
    };

    async scriptProcessing() {
        const priorModelDir = this.hlocMapWorkDirectory + "/prior_model"; // TODO: make sure this is the same as datasetStrayColmapFilteredDir
        const hlocReconstructionDir = this.hlocMapWorkDirectory + "/hloc_reconstruction";
        const hlocConfigFile = this.hlocMapWorkDirectory + "/config.yaml";
        const processingCommand = `python3 hloc_generate_config.py \
            --hloc_dir=${this.config.hlocDir} \
            --input_model_dir ${priorModelDir} \
            --output_dir ${hlocReconstructionDir} \
            --output_config_file ${hlocConfigFile} \
            --feature_conf ${this.settings.featureConf} \
            --matcher_conf ${this.settings.matcherConf} \
            --retrieval_conf ${this.settings.retrievalConf} \
            --pairs_strategy ${this.settings.pairsStrategy}`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export class HlocMapBuildStage extends IdempotentStage {
    constructor(
        private hlocMapWorkDirectory: string,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocMapBuildStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocMapBuild";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocMapBuildStage.stageName,
        title: "Map build",
        scope: "run",
        settings: [],
    };

    async scriptProcessing() {
        const hlocConfigFile = this.hlocMapWorkDirectory + "/config.yaml";
        const processingCommand = `python3 hloc_build_map.py \
            --config_file ${hlocConfigFile}`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export class HlocMapScaleEstimationStage extends IdempotentStage {
    // This stage performs metric alignment (scale estimation) on the reconstructed model
    // It can be run independently from the model building, allowing for quick re-runs
    // if the scale estimation fails

    constructor(
        private hlocMapWorkDirectory: string,
        private settings: HlocMapScaleEstimationSettings,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocMapScaleEstimationStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocMapScaleEstimation";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocMapScaleEstimationStage.stageName,
        title: "Scale estimation",
        scope: "run",
        settings: [
            {
                kind: "enum",
                key: "mode",
                label: "Mode",
                default: "coord_scale_only",
                advanced: true,
                options: ["rescale_model", "coord_scale_only"].map((value) => ({label: value, value})),
            },
            {kind: "integer", key: "minSharedImages", label: "Minimum shared images", default: 4, min: 2, step: 1, advanced: true},
            {kind: "number", key: "minPairDistanceM", label: "Minimum pair distance (m)", default: 0.05, min: 0, step: 0.01, advanced: true},
        ],
    };

    async scriptProcessing() {
        const hlocReconstructionDir = this.hlocMapWorkDirectory + "/hloc_reconstruction";
        const priorModelDir = this.hlocMapWorkDirectory + "/prior_model";
        const transformJsonPath = this.hlocMapWorkDirectory + "/transform.json";

        const processingCommand = `python3 hloc_metric_alignment.py \
            --prior_model_path ${priorModelDir} \
            --reconstruction_path ${hlocReconstructionDir} \
            --transform_json_path ${transformJsonPath} \
            --mode ${this.settings.mode} \
            --min_shared_images ${this.settings.minSharedImages} \
            --min_pair_distance_m ${this.settings.minPairDistanceM}`;
        
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export class HlocMapPlyExportStage extends IdempotentStage {
    constructor(
        private hlocMapWorkDirectory: string,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocMapPlyExportStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocMapPlyExport";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocMapPlyExportStage.stageName,
        title: "PLY export",
        scope: "run",
        settings: [],
    };

    async scriptProcessing() {
        const hlocReconstructionDir = this.hlocMapWorkDirectory + "/hloc_reconstruction";
        const plyPath = this.hlocMapWorkDirectory + "/sparse.ply";
        const processingCommand = `python3 colmap_model_export_ply.py \
            --input_model_dir ${hlocReconstructionDir} \
            --output_ply_path ${plyPath}`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export class HlocMapZipExportStage extends IdempotentStage {
    constructor(
        private hlocMapWorkDirectory: string,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocMapZipExportStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocMapZipExport";

    public static readonly settingsSchema: StageSettingsSchema = {
        stageName: HlocMapZipExportStage.stageName,
        title: "ZIP export",
        scope: "run",
        settings: [],
    };

    async scriptProcessing() {
        const processingCommand = `python3 zip_compress.py \
            --input_dir ${this.hlocMapWorkDirectory}/hloc_reconstruction \
            --zip_path ${this.hlocMapWorkDirectory}/hloc_reconstruction.zip`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}

export const HLOC_PIPELINE_STAGES: HlocStageClass[] = [
    HlocFormatStage,
    HlocImageFilterStage,
    HlocConfigurationStage,
    HlocMapBuildStage,
    HlocMapScaleEstimationStage,
    HlocMapPlyExportStage,
    HlocMapZipExportStage,
];

export function getHlocStageSettingsSchemas(scope?: StageSettingsSchema["scope"]): StageSettingsSchema[] {
    const schemas = HLOC_PIPELINE_STAGES.map((stage) => stage.settingsSchema);
    return scope ? schemas.filter((schema) => schema.scope === scope) : schemas;
}

export function getHlocConfiguredStageSettingsSchemas(scope?: StageSettingsSchema["scope"]): StageSettingsSchema[] {
    return getHlocStageSettingsSchemas(scope).filter((schema) => schema.settings.length > 0);
}

export function getHlocStageSettings(stageSettings: PipelineStageSettings, stageName: string): StageSettingsValues {
    return stageSettings[stageName] ?? {};
}
