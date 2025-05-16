/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { type Invalidator, type Subscriber, type Unsubscriber, writable } from "svelte/store";
import { io, Socket } from "socket.io-client";
import { API_URLS, AUTH_ENABLED } from "./config";
import { getAuthenticationToken } from "./auth";

export interface StoreSubscribable<T> {
    subscribe: (this: void, run: Subscriber<T>, invalidate?: Invalidator<T> | undefined) => Unsubscriber;
}

export type AppState = {
    theme: "light" | "dark";
    setTheme: (theme: "light" | "dark") => void;
    addDialogVisible: boolean;
    setAddDialogVisible: (addDialogVisible: boolean) => void;
    confirmDialog: {
        visible: boolean;
        message: string;
        spinning: boolean;
        callback: () => void;
    };
    setConfirmDialogVisible: (visible: boolean) => void;
    setConfirmDialogSpinning: (spinning: boolean) =>void;
    setConfirmDialogMessage: (message: string) => void;
    setConfirmDialogCallback: (callback: () => void) => void;
    renameDialog: {
        visible: boolean;
        oldName: string;
        callback: (name: string) => void;
    };
    setRenameDialogVisible: (visible: boolean) => void;
    setRenameDialogOldName: (oldName: string) => void;
    setRenameDialogCallback: (callback: (name: string) => void) => void;
};

function createAppStore(): AppState & StoreSubscribable<AppState> {
    const defaultState: AppState = {
        theme: "dark",
        setTheme: (theme: "light" | "dark") => {
            update((state: AppState) => ({ ...state, theme }));
        },
        addDialogVisible: false,
        setAddDialogVisible: (addDialogVisible: boolean) => {
            update((state: AppState) => ({ ...state, addDialogVisible }));
        },
        confirmDialog: {
            visible: false,
            message: "",
            spinning:false,
            callback: () => {},
        },
        setConfirmDialogVisible: (visible: boolean) => {
            update((state: AppState) => ({
                ...state,
                confirmDialog: { ...state.confirmDialog, visible },
            }));
        },
        setConfirmDialogMessage(message) {
            update((state: AppState) => ({
                ...state,
                confirmDialog: { ...state.confirmDialog, message },
            }));
        },
        setConfirmDialogSpinning(spinning) {
            update((state: AppState) => ({
                ...state,
                confirmDialog: { ...state.confirmDialog, spinning },
            }));
        },
        setConfirmDialogCallback(callback) {
            update((state: AppState) => ({
                ...state,
                confirmDialog: { ...state.confirmDialog, callback },
            }));
        },
        renameDialog: {
            visible: false,
            oldName: "",
            callback: () => {},
        },
        setRenameDialogVisible(visible) {
            update((state: AppState) => ({
                ...state,
                renameDialog: { ...state.renameDialog, visible },
            }));
        },
        setRenameDialogOldName(oldName) {
            update((state: AppState) => ({
                ...state,
                renameDialog: { ...state.renameDialog, oldName },
            }));
        },
        setRenameDialogCallback(callback) {
            update((state: AppState) => ({
                ...state,
                renameDialog: { ...state.renameDialog, callback },
            }));
        },
    };

    const { subscribe, update } = writable<AppState>(defaultState);
    return {
        ...defaultState,
        subscribe,
    };
}

export const appStore: AppState & StoreSubscribable<AppState> = createAppStore();

export type LocalizerState = {
    selectedMap: string;
    fetch: () => void;
};

function createLocalizerStore() {
    const defaultState = {
        selectedMap: "",
        async fetch() {
            const headers = new Headers();
            if (AUTH_ENABLED) {
                headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
            }

            const selectedQuery = await fetch(API_URLS.GET_SELECTED_MAP, {
                method: "GET",
                headers: headers,
            });

            if (selectedQuery.ok) {
                const selectedId = await selectedQuery.text();
                update((previousState) => ({
                    ...previousState,
                    selectedMap: selectedId,
                }));
            }
        },
    };
    const { subscribe, update } = writable<LocalizerState>(defaultState);
    return {
        ...defaultState,
        subscribe,
    };
}

export const localizerStore: LocalizerState & StoreSubscribable<LocalizerState> = createLocalizerStore();

// #region Processing Status

export enum TaskStatus {
    notStarted = "Not started",
    active = "Active",
    completed = "Completed",
    failed = "Failed",
}

export interface TaskDescription {
    type: string;
    startTime?: number;
    runTime?: number;
    status: TaskStatus;
    mapId?: string;
}

export interface ProcessMetadata {
    id: string;
    zip: string;
    name: string;
    size: number;
}

export interface PointCloudCreationState {
    status: TaskStatus;
    tasks: Map<string, TaskDescription>;
}

export interface HlocCreationState extends PointCloudCreationState {
    mapId: string;
    mappingConfig: any;
}

export interface Workflow {
    metadata: ProcessMetadata;
    stages: Map<string, TaskDescription>;
}

export type FrontendStatusUpdate = TaskDescription & ProcessMetadata & any;

export type ProcessingState = {
    isLoading: boolean;
    error: Error | undefined;
    value: Array<Workflow>;
    fetch: () => void;
};

let _processingStoreUpdate: (fn: (state: ProcessingState) => ProcessingState) => void;
function createProcessingStore(): ProcessingState & StoreSubscribable<ProcessingState> {
    const defaultState: ProcessingState = {
        isLoading: false,
        error: undefined,
        value: [],
        fetch: () => {
            update((state: ProcessingState) => ({
                ...state,
                isLoading: true,
                value: [],
                error: undefined,
            }));

            const headers = new Headers();
            if (AUTH_ENABLED) {
                headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
            }

            fetch(API_URLS.GET_MAPS, {
                method: "GET",
                headers: headers,
            })
                .then(
                    async (resp: Response) => {
                        if (resp.ok) {
                            const responseObject = await resp.json();
                            update((state: ProcessingState) => {
                                const workflows = [];
                                for (const oldWorkflow of responseObject.statuses) {
                                    let metadata: ProcessMetadata | undefined;
                                    let stages = new Map<string, TaskDescription>();

                                    for (const [key, value] of Object.entries(oldWorkflow)) {
                                        if (key === "metadata") {
                                            metadata = value as ProcessMetadata;
                                        } else if (key === "hloc") {
                                            const hloc = value as {
                                                tasks?: Record<string, TaskDescription>;
                                                mapId: string;
                                            }[];
                                            for (const hlocMap of hloc) {
                                                const { mapId, tasks } = hlocMap;
                                                const shortMapId = mapId.substring(0, 8);
                                                if (tasks) {
                                                    for (const [taskName, task] of Object.entries(
                                                        tasks,
                                                    )) {
                                                        task.mapId = mapId;
                                                        const mapKey = `(${shortMapId}) ${taskName}`;
                                                        stages.set(mapKey, task);
                                                    }
                                                }
                                            }
                                        } else {
                                            stages.set(key, value as TaskDescription);
                                        }
                                    }
                                    if (!metadata) {
                                        metadata = {
                                            id: "UNKNOWN",
                                            name: "UNKNOWN",
                                            zip: "UNKNOWN",
                                            size: 0,
                                        };
                                    }
                                    let newWorkflow: Workflow = {
                                        metadata,
                                        stages,
                                    };

                                    workflows.push(newWorkflow);
                                }
                                return {
                                    ...state,
                                    isLoading: false,
                                    value: workflows,
                                };
                            });
                        } else {
                            if (resp.status === 401) {
                                window.location.replace("/auth/signin");
                            } else {
                                update((state: ProcessingState) => ({
                                    ...state,
                                    isLoading: false,
                                    error: new Error(`${resp.status} - ${resp.statusText}`),
                                }));
                            }
                        }
                    },
                    (reason: any) => {
                        update((state: ProcessingState) => ({
                            ...state,
                            isLoading: false,
                            error: new Error(String(reason)),
                        }));
                    },
                )
                .catch((err: Error) => {
                    console.error(err);
                    update((state: ProcessingState) => ({
                        ...state,
                        isLoading: false,
                        error: err,
                    }));
                });
        },
    };

    const { subscribe, update } = writable<ProcessingState>(defaultState);
    _processingStoreUpdate = update;
    return {
        ...defaultState,
        subscribe,
    };
}

export const processingStore: ProcessingState & StoreSubscribable<ProcessingState> =
    createProcessingStore();

let socket: Socket | undefined;

export function connectSocket() {
    const socketOptions: any = {};
    if (AUTH_ENABLED) {
        socketOptions.auth = {
            token: getAuthenticationToken(),
        };
    }
    socket = io(API_URLS.WEBSOCKET, socketOptions);
    socket.on("connect", () => {
        console.log("Connected to socket");
    });
    socket.on("disconnect", () => {
        console.log("Disconnected from socket");
    });
    socket.on("metadataUpdate", (msg: string) => {
        const metadataUpdate: ProcessMetadata = JSON.parse(msg);
        console.log("metadataUpdate: ", metadataUpdate);
        _processingStoreUpdate((state: ProcessingState) => {
            const foundIndex: number = state.value.findIndex(
                (value: Workflow) => value.metadata.id === metadataUpdate.id,
            );
            if (foundIndex === -1) {
                console.error("metadataUpdate", "ID not found");
            } else {
                const workflow = state.value[foundIndex];
                workflow.metadata = metadataUpdate;
            }
            return { ...state };
        });
    });
    socket.on("processingUpdate", (msg: string) => {
        console.log("Processing update:", msg);
        try {
            const statusUpdate = JSON.parse(msg) as FrontendStatusUpdate;
            console.log("processingStatus: ", statusUpdate);
            if(statusUpdate.type === "datasetThumbnail" && statusUpdate.status === TaskStatus.completed){
                processingStore.fetch();
            }
            _processingStoreUpdate((state: ProcessingState) => {
                const foundIndex: number = state.value.findIndex(
                    (value: Workflow) => value.metadata.id === statusUpdate.id,
                );
                const newStatus: TaskDescription = {
                    type: statusUpdate.type,
                    status: statusUpdate.status,
                    startTime: statusUpdate.startTime,
                    runTime: statusUpdate.runTime,
                    mapId: statusUpdate.mapId,
                };
                if (foundIndex === -1) {
                    // Completely new file
                    const { id, zip, name, size } = statusUpdate;
                    const newWorkflow: Workflow = {
                        metadata: { id, zip, name, size },
                        stages: new Map(),
                    };
                    newWorkflow.stages.set(statusUpdate.type, newStatus);
                    return {
                        ...state,
                        value: [...state.value, newWorkflow],
                    };
                } else {
                    let mapKey = statusUpdate.type;
                    if (statusUpdate.mapId) {
                        const shortMapId = statusUpdate.mapId.substring(0, 8);
                        mapKey = `(${shortMapId}) ${statusUpdate.type}`;
                    }
                    state.value[foundIndex].stages.set(mapKey, newStatus);
                    return {
                        ...state,
                    };
                }
            });
        } catch (err) {
            console.error(err, "Socket message not JSON:", msg);
        }
    });
}

export function disconnectSocket() {
    if (socket) {
        socket.disconnect();
        socket = undefined;
    }
}
// #endregion
