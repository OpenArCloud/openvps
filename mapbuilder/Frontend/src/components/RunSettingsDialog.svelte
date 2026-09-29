<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Button } from "$lib/components/ui/button";
    import * as Dialog from "$lib/components/ui/dialog";
    import { appStore, pipelineSettingsStore, type PipelineStageSettings } from "../stores";
    import PipelineSettingsForm from "./PipelineSettingsForm.svelte";

    let values: PipelineStageSettings = {};

    const onOpenChange = (isOpen: boolean) => {
        if (isOpen) {
            // Snapshot once on open; a reactive block here would reset edits whenever the store updates
            values = Object.fromEntries(
                $pipelineSettingsStore.value
                    .filter((group) => group.scope === "run")
                    .map((group) => [group.stageName, { ...group.values, ...($appStore.runSettingsDialog.initial[group.stageName] ?? {}) }]),
            );
        }
        appStore.setRunSettingsDialogVisible(isOpen);
    };

    function onStart() {
        $appStore.runSettingsDialog.callback(values);
        $appStore.setRunSettingsDialogVisible(false);
    }
</script>

<Dialog.Root open={$appStore.runSettingsDialog.visible} {onOpenChange}>
    <Dialog.Content class="sm:max-w-[620px]">
        <Dialog.Header>
            <Dialog.Title>HLOC Processing Settings</Dialog.Title>
            <Dialog.Description>Settings for this processing run.</Dialog.Description>
        </Dialog.Header>
        <div class="max-h-[60vh] overflow-y-auto py-4 pr-2">
            <PipelineSettingsForm
                groups={$pipelineSettingsStore.value}
                scopes={["run"]}
                completedStages={$appStore.runSettingsDialog.completedStages}
                bind:values
            />
        </div>
        <Dialog.Footer>
            <Button variant="outline" on:click={() => $appStore.setRunSettingsDialogVisible(false)}>Cancel</Button>
            <Button on:click={onStart}>Start</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>