/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {SpawnOptions} from "child_process";
import child_process from "node:child_process";

export class ScriptExecutor {
    protected scriptsDirOpts: SpawnOptions;

    constructor(scriptsDir: string) {
        this.scriptsDirOpts = {
            cwd: scriptsDir,
            stdio: "inherit",
        };
    }

    public async executeCommand(command: string, shell: string) {
        console.log(` [task] Working directory: ${this.scriptsDirOpts.cwd}`);
        console.log(` [task] Executing command: ${command}`);

        await new Promise((resolve, reject) => {
            const runningCommand = child_process.spawn(shell, ["-c", command], this.scriptsDirOpts);

            runningCommand.on("close", (code) => {
                console.log(`child process close all stdio with code ${code}`);
                if (code != 0) {
                    reject(code);
                }
                resolve(code);
            });

            runningCommand.on("error", (error: Error) => {
                console.log("child process close with error " + error.message);
                reject(error);
            });
        });
    }
}
