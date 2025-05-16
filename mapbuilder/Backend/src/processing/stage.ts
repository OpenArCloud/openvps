/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import {TaskDescription, TaskStatus, StageUpdatePublisher} from "../dataSet";
import {ScriptExecutor} from "./scriptexecutor";

export abstract class ProcessingStage extends ScriptExecutor {
    protected state: TaskDescription;

    constructor(
        protected taskName: string,
        scriptsDir: string,
        taskState: TaskDescription | undefined,
    ) {
        super(scriptsDir);

        if (taskState) {
            this.state = taskState;
        } else {
            this.state = {
                type: this.taskName,
                status: TaskStatus.notStarted,
            };
        }
    }

    abstract execute(): Promise<TaskStatus.completed | TaskStatus.failed>;
}

export abstract class IdempotentStage extends ProcessingStage {
    constructor(
        protected taskName: string,
        scriptsDir: string,
        private publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(taskName, scriptsDir, taskState);
    }

    public execute = async () => {
        const processStartTime = Date.now();

        this.state.startTime = processStartTime;
        this.state.status = TaskStatus.active;

        this.publishTaskStatus(this.state);

        try {
            await this.scriptProcessing();
        } catch (error) {
            console.log(` [${this.taskName}] error occured ${error}`);

            this.state.status = TaskStatus.failed;

            this.publishTaskStatus(this.state);
            return TaskStatus.failed;
        }
        const processRunTime = Date.now() - processStartTime;

        this.state.runTime = processRunTime;
        this.state.status = TaskStatus.completed;

        this.publishTaskStatus(this.state);
        return TaskStatus.completed;
    };

    abstract scriptProcessing(): Promise<void>;
}

export abstract class ModifyingStage extends ProcessingStage {
    constructor(
        taskName: string,
        scriptsDir: string,
        private publishTaskStatus: StageUpdatePublisher,
        taskState: TaskDescription | undefined,
    ) {
        super(taskName, scriptsDir, taskState);
    }

    public execute = async () => {
        const cleanupNecessary: boolean = this.state.status == TaskStatus.active || this.state.status == TaskStatus.failed;

        const processStartTime = Date.now();

        this.state.startTime = processStartTime;
        this.state.status = TaskStatus.active;

        this.publishTaskStatus(this.state);

        try {
            await this.scriptProcessing(cleanupNecessary);
        } catch (error) {
            console.log(` [${this.taskName}] error occured ${error}`);

            this.state.status = TaskStatus.failed;

            this.publishTaskStatus(this.state);
            return TaskStatus.failed;
        }

        const processRunTime = Date.now() - processStartTime;

        this.state.runTime = processRunTime;
        this.state.status = TaskStatus.completed;

        this.publishTaskStatus(this.state);
        return TaskStatus.completed;
    };

    abstract scriptProcessing(cleanup: boolean): Promise<void>;
}
