/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {z} from "zod";

export type StageSettingsScope = "dataset" | "run";

interface BaseSettingDescriptor<T> {
    key: string;
    label: string;
    default: T;
    description?: string;
    advanced?: boolean;
}

export interface NumberSettingDescriptor extends BaseSettingDescriptor<number> {
    kind: "number";
    min?: number;
    max?: number;
    step?: number;
}

export interface IntegerSettingDescriptor extends BaseSettingDescriptor<number> {
    kind: "integer";
    min?: number;
    max?: number;
    step?: number;
}

export interface BooleanSettingDescriptor extends BaseSettingDescriptor<boolean> {
    kind: "boolean";
}

export interface StringSettingDescriptor extends BaseSettingDescriptor<string> {
    kind: "string";
}

export interface EnumSettingOption {
    label: string;
    value: string | number;
}

export interface EnumSettingDescriptor extends BaseSettingDescriptor<string | number> {
    kind: "enum";
    options: EnumSettingOption[];
}

export type SettingDescriptor =
    | NumberSettingDescriptor
    | IntegerSettingDescriptor
    | BooleanSettingDescriptor
    | StringSettingDescriptor
    | EnumSettingDescriptor;

export interface StageSettingsSchema {
    stageName: string;
    title: string;
    scope: StageSettingsScope;
    settings: SettingDescriptor[];
}

export type StageSettingsValues = Record<string, string | number | boolean>;
export type PipelineStageSettings = Record<string, StageSettingsValues>;

function applyNumberBounds(schema: z.ZodNumber, descriptor: NumberSettingDescriptor | IntegerSettingDescriptor) {
    let bounded = schema;
    if (descriptor.min !== undefined) {
        bounded = bounded.min(descriptor.min);
    }
    if (descriptor.max !== undefined) {
        bounded = bounded.max(descriptor.max);
    }
    return bounded.default(descriptor.default);
}

function buildSettingZodSchema(descriptor: SettingDescriptor) {
    switch (descriptor.kind) {
        case "number":
            return applyNumberBounds(z.coerce.number(), descriptor);
        case "integer":
            return applyNumberBounds(z.coerce.number().int(), descriptor);
        case "boolean":
            return z.coerce.boolean().default(descriptor.default);
        case "string":
            return z.string().default(descriptor.default);
        case "enum": {
            const allowedValues = descriptor.options.map((option) => option.value);
            return z
                .union([z.string(), z.number()])
                .refine((value) => allowedValues.includes(value), `${descriptor.label} must be one of ${allowedValues.join(", ")}`)
                .default(descriptor.default);
        }
    }
}

export function buildZodSettingsSchema(settings: SettingDescriptor[]) {
    const shape: Record<string, z.ZodTypeAny> = {};
    for (const setting of settings) {
        shape[setting.key] = buildSettingZodSchema(setting);
    }
    return z.object(shape).strip();
}

export function defaultsOf(schema: StageSettingsSchema): StageSettingsValues {
    return Object.fromEntries(schema.settings.map((setting) => [setting.key, setting.default]));
}

export function resolveStageSettings(schema: StageSettingsSchema, ...layers: Array<unknown | undefined>): StageSettingsValues {
    const merged = Object.assign({}, defaultsOf(schema), ...layers.filter((layer) => typeof layer === "object" && layer !== null));
    return buildZodSettingsSchema(schema.settings).parse(merged) as StageSettingsValues;
}

export function resolvePipelineStageSettings(schemas: StageSettingsSchema[], settingsByStage: unknown | undefined): PipelineStageSettings {
    const valuesByStage = typeof settingsByStage === "object" && settingsByStage !== null ? (settingsByStage as Record<string, unknown>) : {};
    return Object.fromEntries(schemas.map((schema) => [schema.stageName, resolveStageSettings(schema, valuesByStage[schema.stageName])]));
}