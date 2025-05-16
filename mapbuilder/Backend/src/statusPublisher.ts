/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import fs from "fs-extra";
import {Server} from "socket.io";
import {FrontendStatusUpdate, ProcessMetadata, TaskDescription} from "./dataSet";

export class GenericStatusPublisher<PersistedState> {
    constructor(
        private readonly io: Server,
        private readonly statusFileName: string,
        private metadata: ProcessMetadata,
    ) {}

    public publishStatus(task: TaskDescription, fullState: PersistedState, frontendExtra?: any) {
        publishStatusToFrontend(this.metadata, task, this.io, frontendExtra);
        persistStatus<PersistedState>(this.statusFileName, fullState);
    }

    public publishMetadata(fullState: PersistedState) {
        // this.metadata should point to PersistedState.metadata
        this.io.emit("metadataUpdate", JSON.stringify(this.metadata));
        fs.writeFileSync(this.statusFileName, JSON.stringify(fullState, null, 2));
    }
}

export function publishStatusToFrontend(metadata: ProcessMetadata, task: TaskDescription, io: Server, frontendExtra?: any) {
    const frontendUpdate: FrontendStatusUpdate = {...metadata, ...task, ...frontendExtra};

    console.log(` [publishStatus] sending status update: ${JSON.stringify(frontendUpdate)}`);
    io.emit("processingUpdate", JSON.stringify(frontendUpdate));
}

export function persistStatus<PersistedState>(statusFileName: string, fullState: PersistedState) {
    console.log(` [publishStatus] persisting status update: ${JSON.stringify(fullState)}`);

    fs.writeFileSync(statusFileName, JSON.stringify(fullState, null, 2));
}
