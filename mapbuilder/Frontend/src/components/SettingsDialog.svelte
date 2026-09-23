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
    let saving = false;
    let error: Error | undefined;

    const onOpenChange = (isOpen: boolean) => {
        if (isOpen) {
            // Snapshot once on open; a reactive block here would reset edits whenever the store updates
            values = Object.fromEntries($pipelineSettingsStore.value.map((group) => [group.stageName, { ...group.values }]));
        }
        appStore.setSettingsDialogVisible(isOpen);
    };

    async function onSave() {
        saving = true;
        error = undefined;
        try {
            for (const group of $pipelineSettingsStore.value) {
                await pipelineSettingsStore.save(group.stageName, values[group.stageName] ?? group.values);
            }
            $appStore.setSettingsDialogVisible(false);
        } catch (err) {
            error = err as Error;
        } finally {
            saving = false;
        }
    }

    function resetToDefaults() {
        const nextValues = Object.fromEntries(
            $pipelineSettingsStore.value.map((group) => [
                group.stageName,
                Object.fromEntries(group.settings.map((setting) => [setting.key, setting.default])),
            ]),
        );
        values = { ...nextValues };
    }
</script>

<Dialog.Root open={$appStore.settingsDialogVisible} {onOpenChange}>
    <Dialog.Content class="sm:max-w-[620px]">
        <Dialog.Header>
            <Dialog.Title>Pipeline Settings</Dialog.Title>
            <Dialog.Description>Default settings for upcoming uploads and HLOC processing runs.</Dialog.Description>
        </Dialog.Header>
        {#if error}
            <div class="text-sm text-destructive">{String(error)}</div>
        {/if}
        {#if $pipelineSettingsStore.error}
            <div class="text-sm text-destructive">Could not load pipeline settings: {String($pipelineSettingsStore.error)}</div>
        {/if}
        <div class="max-h-[60vh] overflow-y-auto py-4 pr-2">
            <PipelineSettingsForm groups={$pipelineSettingsStore.value} bind:values />
        </div>
        <Dialog.Footer>
            <Button variant="outline" on:click={resetToDefaults} disabled={saving}>Reset to defaults</Button>
            <Button on:click={onSave} disabled={saving}>{saving ? "Saving..." : "Save"}</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>