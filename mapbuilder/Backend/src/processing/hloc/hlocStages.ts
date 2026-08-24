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

export class HlocFormatStage extends IdempotentStage {
    // This stage takes a StrayScanner recording and converts it to Colmap model format

    constructor(
        private uploadLocation: UploadLocation,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocFormatStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocFormat";

    async scriptProcessing() {
        const datasetStrayRecordingDir = this.uploadLocation.getStrayRecordingDir();
        const datasetStrayColmapFullDir = this.uploadLocation.getStrayColmapDir();
        const formatCommand = `python3 stray_to_colmap.py \
            --input_dir ${datasetStrayRecordingDir} \
            --output_dir ${datasetStrayColmapFullDir} \
            --resize_factor 0.5 \
            --rotate_degrees 90 \
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
        private hlocConfigPath: string,
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocConfigurationStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocConfiguration";

    async scriptProcessing() {
        const priorModelDir = this.hlocMapWorkDirectory + "/prior_model"; // TODO: make sure this is the same as datasetStrayColmapFilteredDir
        const hlocReconstructionDir = this.hlocMapWorkDirectory + "/hloc_reconstruction";
        const hlocConfigFile = this.hlocMapWorkDirectory + "/config.yaml";
        const metricAlignmentMode = "coord_scale_only"; // TODO: make this configurable
        const processingCommand = `python3 hloc_generate_config.py \
            --hloc_dir=${this.config.hlocDir} \
            --input_model_dir ${priorModelDir} \
            --output_dir ${hlocReconstructionDir} \
            --output_config_file ${hlocConfigFile} \
            --metric_alignment_mode ${metricAlignmentMode}`;
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
        private config: EnvironmentalConfig,
        publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(HlocMapScaleEstimationStage.stageName, config.scriptsDir, publishTaskStatus, taskState);
    }

    public static readonly stageName = "hlocMapScaleEstimation";

    async scriptProcessing() {
        const hlocReconstructionDir = this.hlocMapWorkDirectory + "/hloc_reconstruction";
        const priorModelDir = this.hlocMapWorkDirectory + "/prior_model";
        const transformJsonPath = this.hlocMapWorkDirectory + "/transform.json";
        const configFile = this.hlocMapWorkDirectory + "/config.yaml";
        
        // Read config to get metric alignment parameters
        const fs = require('fs');
        const yaml = require('js-yaml');
        const configContent = fs.readFileSync(configFile, 'utf8');
        const hlocConfig = yaml.load(configContent) as any;
        
        const mode = (hlocConfig?.hloc_reconstruction?.metric_alignment_mode || 'none').toString().toLowerCase();
        if (mode !== 'rescale_model' && mode !== 'coord_scale_only') {
            throw new Error(`Invalid metric_alignment_mode: ${mode}`);
        }
        
        const minSharedImages = hlocConfig?.hloc_reconstruction?.metric_alignment_min_shared_images || 4;
        const minPairDistanceM = hlocConfig?.hloc_reconstruction?.metric_alignment_min_pair_distance_m || 0.05;
        
        // Call hloc_metric_alignment.py directly
        const processingCommand = `python3 hloc_metric_alignment.py \
            --prior_model_path ${priorModelDir} \
            --reconstruction_path ${hlocReconstructionDir} \
            --transform_json_path ${transformJsonPath} \
            --mode ${mode} \
            --min_shared_images ${minSharedImages} \
            --min_pair_distance_m ${minPairDistanceM}`;
        
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

    async scriptProcessing() {
        const processingCommand = `python3 zip_compress.py \
            --input_dir ${this.hlocMapWorkDirectory}/hloc_reconstruction \
            --zip_path ${this.hlocMapWorkDirectory}/hloc_reconstruction.zip`;
        await this.executeCommand(processingCommand, this.config.shell);
    }
}
