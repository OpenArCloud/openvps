/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {defaultsOf, resolveStageSettings, StageSettingsSchema} from "./stageSettings";

const schema: StageSettingsSchema = {
    stageName: "exampleStage",
    title: "Example stage",
    scope: "run",
    settings: [
        {kind: "number", key: "scale", label: "Scale", default: 0.5, min: 0.1, max: 1},
        {kind: "integer", key: "count", label: "Count", default: 4, min: 1},
        {kind: "enum", key: "mode", label: "Mode", default: "a", options: ["a", "b"].map((value) => ({label: value, value}))},
    ],
};

describe("stageSettings", () => {
    it("derives defaults from descriptors", () => {
        expect(defaultsOf(schema)).toEqual({
            scale: 0.5,
            count: 4,
            mode: "a",
        });
    });

    it("resolves layered settings and drops unknown values", () => {
        expect(resolveStageSettings(schema, {scale: 0.7, unknown: "ignored"}, {count: "6"})).toEqual({
            scale: 0.7,
            count: 6,
            mode: "a",
        });
    });

    it("rejects invalid enum values", () => {
        expect(() => resolveStageSettings(schema, {mode: "c"})).toThrow();
    });

    it("rejects out-of-range numeric values", () => {
        expect(() => resolveStageSettings(schema, {scale: 2})).toThrow();
    });
});