/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import fs from "fs-extra";
import path from "node:path";
import {PipelineStageSettings, resolveStageSettings, StageSettingsSchema, StageSettingsValues} from "./stageSettings";

export interface StageSettingsView extends StageSettingsSchema {
    values: StageSettingsValues;
}

export class StageSettingsStore {
    constructor(private settingsDir: string, private schemas: StageSettingsSchema[]) {}

    public getAll(): PipelineStageSettings {
        return Object.fromEntries(this.schemas.map((schema) => [schema.stageName, this.get(schema.stageName)]));
    }

    public get(stageName: string): StageSettingsValues {
        const schema = this.getSchema(stageName);
        const saved = this.readSettingsFile(stageName);
        return resolveStageSettings(schema, saved);
    }

    public getViews(): StageSettingsView[] {
        return this.schemas
            .filter((schema) => schema.settings.length > 0)
            .map((schema) => ({
                ...schema,
                values: this.get(schema.stageName),
            }));
    }

    public save(stageName: string, values: unknown): StageSettingsValues {
        const schema = this.getSchema(stageName);
        const resolved = resolveStageSettings(schema, values);
        fs.ensureDirSync(this.settingsDir);
        fs.writeFileSync(this.getSettingsFilePath(stageName), JSON.stringify(resolved, null, 2));
        return resolved;
    }

    public resolve(schemas: StageSettingsSchema[], overrides?: unknown): PipelineStageSettings {
        const settingsByStage = typeof overrides === "object" && overrides !== null ? (overrides as Record<string, unknown>) : {};
        return Object.fromEntries(
            schemas.map((schema) => [schema.stageName, resolveStageSettings(schema, this.get(schema.stageName), settingsByStage[schema.stageName])]),
        );
    }

    private getSchema(stageName: string): StageSettingsSchema {
        const schema = this.schemas.find((candidate) => candidate.stageName === stageName);
        if (!schema) {
            throw new Error(`Unknown stage settings: ${stageName}`);
        }
        return schema;
    }

    private readSettingsFile(stageName: string): unknown | undefined {
        const settingsPath = this.getSettingsFilePath(stageName);
        if (!fs.existsSync(settingsPath)) {
            return undefined;
        }

        try {
            return JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
        } catch (error) {
            console.warn(` [settings] Ignoring invalid settings file ${settingsPath}: ${error}`);
            return undefined;
        }
    }

    private getSettingsFilePath(stageName: string) {
        return path.join(this.settingsDir, `${stageName}.json`);
    }
}