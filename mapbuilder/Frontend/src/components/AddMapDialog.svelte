<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    /**
     * Copyright 2025 Nokia
     * Licensed under the MIT License.
     * SPDX-License-Identifier: MIT
     */

    import { Button } from "$lib/components/ui/button";
    import * as Dialog from "$lib/components/ui/dialog";
    import { Input } from "$lib/components/ui/input";
    import { Label } from "$lib/components/ui/label";
    import { appStore } from "../stores";
    import { API_URLS, AUTH_ENABLED } from "../config";
    import { getAuthenticationToken } from "../auth";

    let files: FileList | undefined;
    let mapName: string = "";
    let uploadDisabled: boolean = true;
    let uploading = false;
    let uploadProgress: number | undefined;
    let selectedFile = "Choose File";
    let fileInputDom: HTMLInputElement | undefined;
    $: {
        uploadDisabled = files === undefined || files.length === 0 || !mapName;
        if (files) {
            selectedFile = files[0].name;
        } else {
            selectedFile = "Choose File";
        }
    }

    const onFakeFileInputClick = () => {
        fileInputDom?.click();
    };

    const onOpenChange = (isOpen: boolean) => {
        appStore.setAddDialogVisible(isOpen);
    };

    async function onUploadStrayRecordingZip() {
        if (!files) {
            return;
        }
        uploading = true;
        uploadProgress = 0;
        const headers = new Headers();
        const formData = new FormData();
        formData.append("file-content", files[0]);
        formData.append("map-name", mapName);

        if (AUTH_ENABLED) {
            headers.set("Authorization", `Bearer ${getAuthenticationToken()}`);
        }

        try {
            const response = await new Promise<XMLHttpRequest>((resolve, reject) => {
                const request = new XMLHttpRequest();
                request.open("POST", API_URLS.UPLOAD_STRAY_RECORDING_ZIP);
                headers.forEach((value, key) => request.setRequestHeader(key, value));
                request.upload.addEventListener("progress", (event) => {
                    uploadProgress = event.lengthComputable
                        ? Math.round((event.loaded / event.total) * 100)
                        : undefined;
                });
                request.addEventListener("load", () => resolve(request));
                request.addEventListener("error", () => reject(new Error("Upload request failed")));
                request.addEventListener("abort", () => reject(new Error("Upload was cancelled")));
                request.send(formData);
            });

            if (response.status >= 200 && response.status < 300) {
                files = undefined;
                mapName = "";
                $appStore.setAddDialogVisible(false);
            }
        } catch (err) {
            alert("Upload Failed " + err);
        } finally {
            uploading = false;
            uploadProgress = undefined;
        }
    }
</script>

<Dialog.Root
    closeOnOutsideClick={false}
    bind:open={$appStore.addDialogVisible}
    {onOpenChange}
    closeOnEscape={false}
>
    <Dialog.Content class="sm:max-w-[425px]">
        <Dialog.Header>
            <Dialog.Title>Upload New Map</Dialog.Title>
            <Dialog.Description>Upload new point cloud for processing</Dialog.Description>
        </Dialog.Header>
        <div class="grid gap-4 py-4">
            <div class="grid grid-cols-4 items-center gap-4">
                <Label for="name" class="text-right">Name</Label>
                <Input id="name" class="col-span-3" required bind:value={mapName} />
            </div>
            <div class="grid grid-cols-4 items-center gap-4">
                <Label for="fileInput" class="text-right">Zip File</Label>
                <div class="fileInputContainer col-span-3">
                    <input
                        id="fileInput"
                        type="file"
                        accept="application/zip"
                        class="fileInput"
                        required
                        bind:files
                        bind:this={fileInputDom}
                    />
                    <!-- shadcn Input for file did not work-->
                    <Input
                        id="filenameDisplay"
                        type="text"
                        class="col-span-3"
                        style="cursor: default"
                        readonly
                        bind:value={selectedFile}
                        on:click={onFakeFileInputClick}
                    />
                </div>
            </div>
        </div>
        <div class="text-xs italic">
            The recordings are stored only for map generation purposes. You can delete them at any
            time.
        </div>
        <Dialog.Footer class="uploadFooter">
            <Button
                type="submit"
                disabled={uploadDisabled || uploading}
                on:click={onUploadStrayRecordingZip}
            >
                {#if uploading}
                    Uploading...
                {:else}
                    Upload
                {/if}
            </Button>
            {#if uploading}
                <div
                    class:indeterminate={uploadProgress === undefined}
                    class="uploadProgress"
                    role="progressbar"
                    aria-label="Upload progress"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={uploadProgress}
                >
                    <div class="uploadProgressValue" style:width={`${uploadProgress ?? 100}%`} />
                </div>
            {/if}
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .fileInputContainer {
        position: relative;
    }
    .fileInput {
        display: none;
    }
    :global(.uploadFooter) {
        flex-direction: column;
        align-items: stretch;
        gap: 0.5rem;
    }
    .uploadProgress {
        position: relative;
        width: 100%;
        height: 0.5rem;
        overflow: hidden;
        border-radius: 9999px;
        background-color: hsl(var(--muted));
    }
    .uploadProgressValue {
        height: 100%;
        border-radius: inherit;
        background-color: hsl(var(--primary));
        transition: width 150ms ease-out;
    }
    .uploadProgress.indeterminate .uploadProgressValue {
        width: 40%;
        animation: uploadProgress 1.2s ease-in-out infinite;
    }
    @keyframes uploadProgress {
        0% {
            transform: translateX(-100%);
        }
        100% {
            transform: translateX(250%);
        }
    }

</style>
