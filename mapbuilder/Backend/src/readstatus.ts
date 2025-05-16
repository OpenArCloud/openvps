/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import fs from "fs-extra";
import path from "node:path";
import {DataSetStatus, TaskStatus} from "./dataSet";

export const parseStatusFiles = (uploadsRoot: string): DataSetStatus[] => {
    const statusStrings = readStatusFiles(uploadsRoot);
    const parsedStatuses = parseStatuses(statusStrings);

    for (const dataSetStatus of parsedStatuses) {
        if (dataSetStatus.hloc) {
            for (const hlocProcess of dataSetStatus.hloc) {
                if (hlocProcess.tasks.hlocFormat.status === TaskStatus.active) {
                    console.log(` [parseStatus] task ${dataSetStatus.metadata.id} stopped in a previous run, setting Format status to Failed`);
                    hlocProcess.tasks.hlocFormat.status = TaskStatus.failed;
                }

                if (hlocProcess.tasks.hlocMapBuild.status === TaskStatus.active) {
                    console.log(` [parseStatus] task ${dataSetStatus.metadata.id} stopped in a previous run, setting Process status to Failed`);
                    hlocProcess.tasks.hlocMapBuild.status = TaskStatus.failed;
                }
            }
        }
    }

    return parsedStatuses;
};

export const parseStatuses = (statuses: string[]): DataSetStatus[] => {
    const parsedStatuses = statuses.map((status) => {
        const processStatus: DataSetStatus = JSON.parse(status);
        return processStatus;
    });

    return parsedStatuses;
};

export const readStatusFiles = (uploadsRoot: string): string[] => {
    const statusStrings = fs
        .readdirSync(uploadsRoot)
        .filter((filename) => fs.existsSync(path.join(uploadsRoot, filename, "status.json")))
        .map((filename) => path.join(uploadsRoot, filename, "status.json"))
        .map((file) => {
            return fs.readFileSync(file, "utf-8");
        });
    return statusStrings;
};
