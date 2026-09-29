<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Input } from "$lib/components/ui/input";
    import { Label } from "$lib/components/ui/label";
    import type { SettingDescriptor } from "../stores";

    export let setting: SettingDescriptor;
    export let value: string | number | boolean;
    export let disabled = false;
    export let onValueChange: (value: string | number | boolean) => void = () => {};

    function setValue(newValue: string | number | boolean) {
        value = newValue;
        onValueChange(newValue);
    }

    function onSelectChange(event: Event) {
        const selectedValue = (event.currentTarget as HTMLSelectElement).value;
        const selectedOption = setting.options?.find((option) => String(option.value) === selectedValue);
        setValue(selectedOption?.value ?? selectedValue);
    }

    function onInputChange(event: Event) {
        const input = event.currentTarget as HTMLInputElement;
        if (setting.kind === "number" || setting.kind === "integer") {
            setValue(input.valueAsNumber);
        } else {
            setValue(input.value);
        }
    }

    function onCheckboxChange(event: Event) {
        setValue((event.currentTarget as HTMLInputElement).checked);
    }
</script>

<div class="grid grid-cols-4 items-center gap-4">
    <Label class="text-right" for={setting.key}>{setting.label}</Label>
    {#if setting.kind === "enum"}
        <select class="settingInput col-span-3" id={setting.key} {disabled} value={String(value)} on:change={onSelectChange}>
            {#each setting.options ?? [] as option}
                <option value={String(option.value)}>{option.label}</option>
            {/each}
        </select>
    {:else if setting.kind === "boolean"}
        <input class="h-4 w-4" id={setting.key} type="checkbox" {disabled} checked={Boolean(value)} on:change={onCheckboxChange} />
    {:else}
        <Input
            id={setting.key}
            class="col-span-3"
            type={setting.kind === "string" ? "text" : "number"}
            {disabled}
            min={setting.min}
            max={setting.max}
            step={setting.step}
            value={value}
            on:input={onInputChange}
        />
    {/if}
    {#if setting.description}
        <span class="col-start-2 col-span-3 text-xs text-muted-foreground">{setting.description}</span>
    {/if}
</div>

<style>
    .settingInput {
        display: flex;
        height: 2.5rem;
        width: 100%;
        border-radius: calc(var(--radius) - 2px);
        border: 1px solid hsl(var(--input));
        background-color: hsl(var(--background));
        padding: 0 0.75rem;
        font-size: 0.875rem;
    }
</style>