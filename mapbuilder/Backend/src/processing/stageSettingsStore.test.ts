/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import fs from "fs-extra";
import os from "node:os";
import path from "node:path";
import {StageSettingsSchema} from "./stageSettings";
import {StageSettingsStore} from "./stageSettingsStore";

const schemas: StageSettingsSchema[] = [
    {
        stageName: "firstStage",
        title: "First stage",
        scope: "dataset",
        settings: [{kind: "number", key: "resizeFactor", label: "Resize factor", default: 0.5, min: 0.01, max: 1}],
    },
    {
        stageName: "secondStage",
        title: "Second stage",
        scope: "run",
        settings: [{kind: "enum", key: "mode", label: "Mode", default: "a", options: ["a", "b"].map((value) => ({label: value, value}))}],
    },
];

describe("StageSettingsStore", () => {
    let settingsDir: string;

    beforeEach(() => {
        settingsDir = fs.mkdtempSync(path.join(os.tmpdir(), "stage-settings-"));
    });

    afterEach(() => {
        fs.rmSync(settingsDir, {recursive: true, force: true});
    });

    it("returns defaults when a stage settings file is missing", () => {
        const store = new StageSettingsStore(settingsDir, schemas);

        expect(store.get("firstStage")).toEqual({resizeFactor: 0.5});
    });

    it("saves only the requested stage", () => {
        const store = new StageSettingsStore(settingsDir, schemas);

        store.save("firstStage", {resizeFactor: 0.25});

        expect(fs.existsSync(path.join(settingsDir, "firstStage.json"))).toBe(true);
        expect(fs.existsSync(path.join(settingsDir, "secondStage.json"))).toBe(false);
        expect(store.get("firstStage")).toEqual({resizeFactor: 0.25});
    });

    it("ignores corrupt settings files and falls back to defaults", () => {
        fs.ensureDirSync(settingsDir);
        fs.writeFileSync(path.join(settingsDir, "secondStage.json"), "not-json");
        const store = new StageSettingsStore(settingsDir, schemas);

        expect(store.get("secondStage")).toEqual({mode: "a"});
    });

    it("ignores orphan files for removed stages", () => {
        fs.ensureDirSync(settingsDir);
        fs.writeFileSync(path.join(settingsDir, "removedStage.json"), JSON.stringify({mode: "b"}));
        const store = new StageSettingsStore(settingsDir, schemas);

        expect(store.getAll()).toEqual({
            firstStage: {resizeFactor: 0.5},
            secondStage: {mode: "a"},
        });
    });

});