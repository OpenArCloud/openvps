/**
 * Copyright 2026 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import fs from "fs-extra";
import path from "node:path";
import {DataSetStatus} from "./dataSet";
import {EnvironmentalConfig} from "./index";
import {HlocMapCoverageStage, HlocMapCoverageSettings} from "./processing/hloc/hlocStages";
import {PipelineStageSettings, resolveStageSettings} from "./processing/stageSettings";
import {ScriptExecutor} from "./processing/scriptexecutor";

export function resolveCoverageSettings(stageSettings?: PipelineStageSettings): HlocMapCoverageSettings {
    return resolveStageSettings(
        HlocMapCoverageStage.settingsSchema,
        stageSettings?.[HlocMapCoverageStage.stageName],
    ) as HlocMapCoverageSettings;
}

export function coverageSettingsForMap(
    uploadsDir: string,
    datasetId: string,
    mapId: string,
    inMemoryStatus?: DataSetStatus,
): HlocMapCoverageSettings {
    const fromMemory = inMemoryStatus?.hloc?.find((h) => h.mapId === mapId)?.stageSettings;
    if (fromMemory) {
        return resolveCoverageSettings(fromMemory);
    }
    const statusPath = path.join(uploadsDir, datasetId, "status.json");
    if (fs.existsSync(statusPath)) {
        try {
            const status = fs.readJsonSync(statusPath) as DataSetStatus;
            const fromDisk = status.hloc?.find((h) => h.mapId === mapId)?.stageSettings;
            return resolveCoverageSettings(fromDisk);
        } catch (error) {
            console.error("[coverage] failed to read status.json for settings", statusPath, error);
        }
    }
    return resolveCoverageSettings(undefined);
}

export function readHlocCoveragePath(dataSetId: string, mapId: string, config: EnvironmentalConfig): string {
    return path.join(config.uploadsDir, dataSetId, "hlocMaps", mapId, "coverage.json");
}

export function readHlocCoverage(
    dataSetId: string,
    mapId: string,
    config: EnvironmentalConfig,
): Record<string, unknown> | null {
    const coveragePath = readHlocCoveragePath(dataSetId, mapId, config);
    if (!fs.existsSync(coveragePath)) {
        return null;
    }
    try {
        const raw = fs.readJsonSync(coveragePath);
        return typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : null;
    } catch (error) {
        console.error("[coverage] read failed", coveragePath, error);
        return null;
    }
}

function coveragePresetFlag(settings: HlocMapCoverageSettings): "indoor" | "outdoor" {
    return settings.preset === "indoor" ? "indoor" : "outdoor";
}

const COVERAGE_PRESET_MAX_HORIZ_M: Record<"indoor" | "outdoor", number> = {
    outdoor: 50,
    indoor: 15,
};

/** Omit radius on CLI when unset in the GUI (schema default 50) or equal to the preset cap. */
function maxHorizRadiusCliArg(settings: HlocMapCoverageSettings): number | undefined {
    const preset = coveragePresetFlag(settings);
    const presetCap = COVERAGE_PRESET_MAX_HORIZ_M[preset];
    if (settings.maxHorizRadiusM === presetCap) {
        return undefined;
    }
    if (preset === "indoor" && settings.maxHorizRadiusM === 50) {
        return undefined;
    }
    return settings.maxHorizRadiusM;
}

export async function runMapCoverageCompute(
    mapWorkDir: string,
    mapId: string,
    config: EnvironmentalConfig,
    settings: HlocMapCoverageSettings,
): Promise<void> {
    const executor = new ScriptExecutor(config.scriptsDir);
    const colmapModelDir = path.join(mapWorkDir, "hloc_reconstruction");
    const transformPath = path.join(mapWorkDir, "transform.json");
    const outputPath = path.join(mapWorkDir, "coverage.json");
    const preset = coveragePresetFlag(settings);
    const maxHoriz = maxHorizRadiusCliArg(settings);
    const cmd =
        `python3 compute_map_coverage.py` +
        ` --map_id "${mapId}"` +
        ` --colmap_model_dir "${colmapModelDir}"` +
        ` --transform_path "${transformPath}"` +
        ` --output "${outputPath}"` +
        ` --preset ${preset}` +
        ` --min_track_len ${settings.minTrackLen}` +
        ` --max_reproj_error_px ${settings.maxReprojErrorPx}` +
        (maxHoriz !== undefined ? ` --max_horiz_radius_m ${maxHoriz}` : "") +
        ` --horiz_percentile ${settings.horizPercentile}`;
    await executor.executeCommand(cmd, config.shell);
}

export function notifyMapRegistry(datasetId: string, mapId: string): void {
    const base = process.env.MAPREGISTRY_URL;
    if (!base) {
        return;
    }
    const url = `${base.replace(/\/$/, "")}/internal/reload`;
    fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({dataset_id: datasetId, map_id: mapId}),
    }).catch((e) => console.error("[mapregistry] coverage notify failed", e));
}

export async function computeMapCoverageAndNotify(
    datasetId: string,
    mapId: string,
    mapWorkDir: string,
    config: EnvironmentalConfig,
    settings: HlocMapCoverageSettings,
): Promise<void> {
    await runMapCoverageCompute(mapWorkDir, mapId, config, settings);
    notifyMapRegistry(datasetId, mapId);
}