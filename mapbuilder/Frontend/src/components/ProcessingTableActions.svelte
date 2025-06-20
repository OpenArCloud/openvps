<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import DownloadSvg from "../svg/download.svelte";
    import PlaySvg from "../svg/playCircle.svelte";
    import TrashSvg from "../svg/trash.svelte";
    import PencilSvg from "../svg/pencil.svelte";
    import { Button } from "$lib/components/ui/button";
    import * as Tooltip from "$lib/components/ui/tooltip";
    import { appStore, localizerStore, processingStore, TaskStatus } from "../stores";
    import { API_URLS, AUTH_ENABLED } from "../config";
    import MessageDialog from "./MessageDialog.svelte";
    import { getAuthenticationToken } from "../auth";
    import OpenAligner from "../svg/openAligner.svelte";
    import Pin from "../svg/pin.svelte";

    export let id: string;
    export let name: string;
    export let onLoading: (loading: boolean) => void;
    let error: Error | undefined;

    let enableHlocStartProcessing: boolean = false;
    let enableHlocDownloadMap: boolean = false;

    $: processingState = $processingStore.value.find((state) => state.metadata.id === id);
    $: if (processingState) {
        const extractStage = processingState.stages.get("extract");
        const isExtractCompleted = extractStage?.status === TaskStatus.completed;
        enableHlocStartProcessing = false;
        enableHlocDownloadMap = false;

        const lastHlocMapId = [...processingState.stages.values()]
            .filter((task) => task.type?.includes("hloc"))
            .at(-1)?.mapId;
        if (lastHlocMapId) {
            const lastHlocMapStages = [...processingState.stages.values()].filter(
                (task) => task.mapId === lastHlocMapId,
            );
            const isHlocWorking = lastHlocMapStages.some((task) => task.status === TaskStatus.active);
            const isHlocFinished =
                lastHlocMapStages.find((task) => task.type === "hlocMapPlyExport")?.status ===
                TaskStatus.completed;
            if (isExtractCompleted && !isHlocWorking && !isHlocFinished) {
                enableHlocStartProcessing = true;
            }
            if (isHlocFinished) {
                enableHlocDownloadMap = true;
            }
        } else {
            enableHlocStartProcessing = true;
        }
    }

    function getFirstHlocMapId() {
        const hlocStageValues = [...processingState!.stages.entries()]
            .filter(([key]) => key.endsWith("hlocMapBuild"))
            .map(([_key, value]) => value);
        const hlocMapBuild = hlocStageValues.at(0);
        const mapId = hlocMapBuild!.mapId!;
        return mapId;
    }

    const onHlocStartProcessing = () => {
        error = undefined;
        onLoading(true);
        const headers = new Headers();
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        headers.set("Accept", "application/json, text/plain");
        headers.set("Content-Type", "application/json");

        // TODO: add frontend popup window to specify the config parameters. Parameters are harcoded for now.
        const hlocMappingConfig = {
            feature_conf: "superpoint_aachen",
            matcher_conf: "superglue",
            retrieval_conf: "netvlad",
            pairs_strategy: "from_retrieval",
            optimize_poses: true,
        };
        fetch(API_URLS.HLOC_REGISTER_CONFIG.replace(":id", id), {
            method: "POST",
            headers: headers,
            body: JSON.stringify(hlocMappingConfig),
        })
            .then(
                (response) => {
                    if (response.ok) {
                        response.json().then((data) => {
                            console.log(data);
                            //const data = JSON.parse(jData)
                            const mapId = data["mapId"];
                            console.log("new mapId: ", mapId);
                            if (mapId) {
                                onHlocConfigRegistered(mapId);
                            } else {
                                error = new Error(`Could not parse mapId from response`);
                            }
                        });
                    } else {
                        error = new Error(`${response.status} - ${response.statusText}`);
                    }
                },
                (err) => {
                    error = err;
                },
            )
            .catch((err) => {
                error = err;
            })
            .finally(() => {
                onLoading(false);
            });
    };

    const onHlocConfigRegistered = (mapId: string) => {
        error = undefined;
        onLoading(true);
        const headers = new Headers();
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        fetch(API_URLS.HLOC_START_PROCESSING.replace(":id", id).replace(":mapId", mapId), {
            method: "POST",
            headers: headers,
        })
            .then(
                (resp) => {
                    if (resp.ok) {
                        $processingStore.fetch();
                    } else {
                        error = new Error(`${resp.status} - ${resp.statusText}`);
                    }
                },
                (err) => {
                    error = err;
                },
            )
            .catch((err) => {
                error = err;
            })
            .finally(() => {
                onLoading(false);
            });
    };

    const onHlocDownloadMap = () => {
        let downloadUrl = API_URLS.HLOC_DOWNLOAD_MAP.replace(":id", id);
        const mapId = getFirstHlocMapId();

        downloadUrl = downloadUrl.replace(":mapId", mapId);
        const headers = new Headers();
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        fetch(downloadUrl, {
            method: "GET",
            headers: headers,
        })
            .then(async (response) => {
                const filenameHeader = response.headers
                    .get("Content-Disposition")
                    ?.split("filename=")[1];
                const filename = filenameHeader?.replaceAll(/['"]+/g, "");
                return { blob: await response.blob(), filename };
            })
            .then(({ blob, filename }) => {
                if (!blob || !filename) {
                    console.error("No file received");
                    return;
                }
                let url = window.URL.createObjectURL(blob);
                let a = document.createElement("a");
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
            })
            .catch((err) => {
                console.error(err);
            });
    };

    const onHlocOpenAligner = () => {
        const mapId = getFirstHlocMapId();
        const alignerUrl = API_URLS.MAPALIGNER_URL.replace(":id", mapId).replace(":type", "hloc");
        window.open(alignerUrl, "_blank")?.focus();
    };

    const onTaskRename = (newName: string) => {
        const downloadUrl = API_URLS.RENAME_MAP.replace(":id", id);
        const headers = new Headers();
        headers.set("Content-Type", "application/json");
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        fetch(downloadUrl, {
            method: "PUT",
            headers: headers,
            body: JSON.stringify({
                name: newName,
            }),
        })
            .then((response) => {
                if (!response.ok) {
                    alert("Could not rename task");
                }
                //$processingStore.fetch();
                $appStore.setRenameDialogVisible(false);
            })
            .catch((err) => {
                console.error(err);
            });
    };

    const onTaskRenameClick = () => {
        $appStore.setRenameDialogCallback(onTaskRename);
        $appStore.setRenameDialogOldName(name);
        $appStore.setRenameDialogVisible(true);
    };

    const onTaskSelectClick = () => {
        const downloadUrl = API_URLS.SELECT_MAP.replace(":id", id);
        const headers = new Headers();
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        fetch(downloadUrl, {
            method: "PUT",
            headers: headers,
        })
            .then(async (response) => {
                if (!response.ok) {
                    response.text().then((error) => {
                        alert("Could not select map: " + error);

                        $processingStore.fetch();
                        $localizerStore.fetch();
                    });
                } else {
                    response.text().then((message) => {
                        if (message !== "OK") {
                            alert(message);
                        }

                        $processingStore.fetch();
                        $localizerStore.fetch();
                    });
                }
            })
            .catch((err) => {
                console.error(err);
            });
    };

    const onTaskDelete = () => {
        $appStore.setConfirmDialogSpinning(true);
        const downloadUrl = API_URLS.DELETE_MAP.replace(":id", id);
        const headers = new Headers();
        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        fetch(downloadUrl, {
            method: "DELETE",
            headers: headers,
        })
            .then((response) => {
                if (!response.ok) {
                    alert("Could not delete task");
                }
                $processingStore.fetch();
                $appStore.setConfirmDialogSpinning(false);
                $appStore.setConfirmDialogVisible(false);
            })
            .catch((err) => {
                $appStore.setConfirmDialogSpinning(false);
                console.error(err);
            });
    };

    const onTaskDeleteClick = () => {
        $appStore.setConfirmDialogCallback(onTaskDelete);
        $appStore.setConfirmDialogMessage(`Are you sure want to delete ${name}?`);
        $appStore.setConfirmDialogVisible(true);
    };
</script>

<div class="root">
    {#if error}
        <MessageDialog title="Error" message={String(error)} />
    {/if}

    {#if enableHlocStartProcessing}
        <Tooltip.Root>
            <Tooltip.Trigger>
                <Button
                    variant="ghost"
                    size="icon"
                    class="relative h-8 w-8 p-0"
                    on:click={onHlocStartProcessing}
                >
                    <PlaySvg />
                </Button>
            </Tooltip.Trigger>
            <Tooltip.Content>Start HLOC Processing</Tooltip.Content>
        </Tooltip.Root>
        {#if !enableHlocDownloadMap}
            <br />
        {/if}
    {/if}

    {#if enableHlocDownloadMap}
        <Tooltip.Root>
            <Tooltip.Trigger>
                <Button
                    variant="ghost"
                    size="icon"
                    class="relative h-8 w-8 p-0"
                    on:click={onHlocDownloadMap}
                >
                    <DownloadSvg />
                </Button>
            </Tooltip.Trigger>
            <Tooltip.Content>Download Last HLOC Map</Tooltip.Content>
        </Tooltip.Root>

        <Tooltip.Root>
            <Tooltip.Trigger>
                <Button
                    variant="ghost"
                    size="icon"
                    class="relative h-8 w-8 p-0"
                    on:click={onHlocOpenAligner}
                >
                    <OpenAligner />
                </Button>
            </Tooltip.Trigger>
            <Tooltip.Content>Open Last HLOC Map in Aligner</Tooltip.Content>
        </Tooltip.Root>

        <Tooltip.Root>
            <Tooltip.Trigger>
                <Button
                    variant="ghost"
                    size="icon"
                    class="relative h-8 w-8 p-0"
                    on:click={onTaskSelectClick}
                    disabled={$localizerStore.selectedMap === id}
                >
                    <Pin />
                </Button>
            </Tooltip.Trigger>
            {#if $localizerStore.selectedMap === id}
                <Tooltip.Content>Map already selected in Localizer</Tooltip.Content>
            {:else}
                <Tooltip.Content>Select HLOC Map in Localizer</Tooltip.Content>
            {/if}
        </Tooltip.Root>

        <br />
    {/if}

    <Tooltip.Root>
        <Tooltip.Trigger>
            <Button
                variant="ghost"
                size="icon"
                class="relative h-8 w-8 p-0"
                on:click={onTaskRenameClick}
            >
                <PencilSvg />
            </Button>
        </Tooltip.Trigger>
        <Tooltip.Content>Rename Map</Tooltip.Content>
    </Tooltip.Root>

    <Tooltip.Root>
        <Tooltip.Trigger>
            <Button
                variant="ghost"
                size="icon"
                class="relative h-8 w-8 p-0"
                on:click={onTaskDeleteClick}
            >
                <TrashSvg />
            </Button>
        </Tooltip.Trigger>
        <Tooltip.Content>Delete Map</Tooltip.Content>
    </Tooltip.Root>
</div>

<style lang="postcss">
    .root {
        stroke: theme("colors.secondary.foreground");
    }
</style>
