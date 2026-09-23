<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import StageSettingField from "./StageSettingField.svelte";
    import { Button } from "$lib/components/ui/button";
    import ChevronDownSvg from "../svg/chevronDown.svelte";
    import ResetSvg from "svelte-radix/Reset.svelte";
    import EyeOpenSvg from "svelte-radix/EyeOpen.svelte";
    import EyeClosedSvg from "svelte-radix/EyeClosed.svelte";
    import type { PipelineStageSettings, StageSettingsView } from "../stores";

    export let groups: StageSettingsView[] = [];
    export let scopes: ("dataset" | "run")[] = ["dataset", "run"];
    export let values: PipelineStageSettings = {};
    export let completedStages: string[] = [];
    export let readonly = false;

    let expandedStages: Record<string, boolean> = {};
    let showAdvancedSettings: Record<string, boolean> = {};

    $: visibleGroups = groups.filter((group) => scopes.includes(group.scope));
    $: for (const group of visibleGroups) {
        if (!values[group.stageName]) {
            values = { ...values, [group.stageName]: { ...group.values } };
        }
        if (!(group.stageName in expandedStages)) {
            expandedStages = { ...expandedStages, [group.stageName]: true };
        }
    }

    // `values` must be a direct argument (not just closed over) so Svelte tracks it as a template dependency
    function getValue(currentValues: PipelineStageSettings, group: StageSettingsView, key: string) {
        return currentValues[group.stageName]?.[key] ?? group.settings.find((setting) => setting.key === key)?.default ?? "";
    }

    function updateSetting(stageName: string, key: string, value: string | number | boolean) {
        values = {
            ...values,
            [stageName]: {
                ...(values[stageName] ?? {}),
                [key]: value,
            },
        };
    }

    function onSettingValueChange(stageName: string, key: string) {
        return (value: string | number | boolean) => updateSetting(stageName, key, value);
    }

    function toggleExpanded(stageName: string) {
        expandedStages = { ...expandedStages, [stageName]: !expandedStages[stageName] };
    }

    function toggleAdvanced(stageName: string) {
        showAdvancedSettings = { ...showAdvancedSettings, [stageName]: !showAdvancedSettings[stageName] };
    }

    function hasAdvancedSettings(group: StageSettingsView) {
        return group.settings.some((setting) => setting.advanced);
    }

    // `showAdvancedSettings` must be a direct argument (not just closed over) so Svelte tracks it as a template dependency
    function visibleSettings(currentShowAdvancedSettings: Record<string, boolean>, group: StageSettingsView) {
        return group.settings.filter((setting) => readonly || !setting.advanced || currentShowAdvancedSettings[group.stageName]);
    }

    function resetGroupToDefaults(group: StageSettingsView) {
        values = {
            ...values,
            [group.stageName]: Object.fromEntries(group.settings.map((setting) => [setting.key, setting.default])),
        };
    }
</script>

<div class="space-y-5">
    {#each visibleGroups as group, index}
        {#if index > 0}
            <hr class="stageSeparator" />
        {/if}
        <section class:completed={completedStages.includes(group.stageName)}>
            <div class="mb-3 flex items-center justify-between">
                <div class="flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        class="h-6 w-6 shrink-0 p-0"
                        on:click={() => toggleExpanded(group.stageName)}
                        aria-label={expandedStages[group.stageName] ? `Collapse ${group.title}` : `Expand ${group.title}`}
                    >
                        <span class:collapsed={!expandedStages[group.stageName]} class="chevron">
                            <ChevronDownSvg />
                        </span>
                    </Button>
                    <h3 class="text-sm font-medium">{group.title}</h3>
                </div>
                <div class="flex items-center gap-2">
                    {#if completedStages.includes(group.stageName)}
                        <span class="text-xs text-muted-foreground">already completed</span>
                    {/if}
                    {#if !readonly}
                        {#if hasAdvancedSettings(group)}
                            <Button
                                variant="ghost"
                                size="icon"
                                class="h-6 w-6 shrink-0 p-0"
                                on:click={() => toggleAdvanced(group.stageName)}
                                aria-label={showAdvancedSettings[group.stageName] ? `Hide advanced settings for ${group.title}` : `Show advanced settings for ${group.title}`}
                                title={showAdvancedSettings[group.stageName] ? "Hide advanced settings" : "Show advanced settings"}
                            >
                                {#if showAdvancedSettings[group.stageName]}
                                    <EyeOpenSvg class="h-4 w-4" />
                                {:else}
                                    <EyeClosedSvg class="h-4 w-4" />
                                {/if}
                            </Button>
                        {/if}
                        <Button
                            variant="ghost"
                            size="icon"
                            class="h-6 w-6 shrink-0 p-0"
                            on:click={() => resetGroupToDefaults(group)}
                            disabled={completedStages.includes(group.stageName)}
                            aria-label={`Reset ${group.title} to defaults`}
                            title="Reset to defaults"
                        >
                            <ResetSvg class="h-4 w-4" />
                        </Button>
                    {/if}
                </div>
            </div>
            {#if expandedStages[group.stageName]}
                <div class="grid gap-4">
                    {#each visibleSettings(showAdvancedSettings, group) as setting}
                        <StageSettingField
                            {setting}
                            value={getValue(values, group, setting.key)}
                            disabled={readonly || completedStages.includes(group.stageName)}
                            onValueChange={onSettingValueChange(group.stageName, setting.key)}
                        />
                    {/each}
                </div>
            {/if}
        </section>
    {/each}
</div>

<style>
    .completed {
        opacity: 0.6;
    }
    .stageSeparator {
        border: none;
        border-top: 1px solid hsl(var(--border));
        margin: 0;
    }
    .chevron {
        display: flex;
        transition: transform 150ms ease;
    }
    .chevron.collapsed {
        transform: rotate(-90deg);
    }
</style>