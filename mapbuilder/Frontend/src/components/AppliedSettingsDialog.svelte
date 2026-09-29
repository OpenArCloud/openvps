<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Button } from "$lib/components/ui/button";
    import * as Dialog from "$lib/components/ui/dialog";
    import { appStore, pipelineSettingsStore } from "../stores";
    import PipelineSettingsForm from "./PipelineSettingsForm.svelte";

    const onOpenChange = (isOpen: boolean) => {
        appStore.setAppliedSettingsDialogVisible(isOpen);
    };
</script>

<Dialog.Root open={$appStore.appliedSettingsDialog.visible} {onOpenChange}>
    <Dialog.Content class="sm:max-w-[620px]">
        <Dialog.Header>
            <Dialog.Title>Applied Settings &ndash; {$appStore.appliedSettingsDialog.mapName}</Dialog.Title>
            <Dialog.Description>Settings that were used to create this map. This view is read-only.</Dialog.Description>
        </Dialog.Header>
        <div class="max-h-[60vh] overflow-y-auto py-4 pr-2">
            <PipelineSettingsForm
                groups={$pipelineSettingsStore.value}
                values={$appStore.appliedSettingsDialog.values}
                readonly
            />
        </div>
        <Dialog.Footer>
            <Button variant="outline" on:click={() => appStore.setAppliedSettingsDialogVisible(false)}>Close</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
