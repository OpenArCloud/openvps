<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import AppBar from "./AppBar.svelte";
    import Toolbar from "./Toolbar.svelte";
    import AddMapDialog from "./AddMapDialog.svelte";
    import ProcessingStatus from "./ProcessingStatus.svelte";
    import ConfirmDialog from "./ConfirmDialog.svelte";
    import RenameDialog from "./RenameDialog.svelte";
    import SettingsDialog from "./SettingsDialog.svelte";
    import RunSettingsDialog from "./RunSettingsDialog.svelte";
    import AppliedSettingsDialog from "./AppliedSettingsDialog.svelte";
    import { onMount } from "svelte";
    import { pipelineSettingsStore } from "../stores";

    onMount(() => {
        pipelineSettingsStore.fetch();
    });
</script>

<div>
    <AppBar />
    <Toolbar />
    <AddMapDialog />
    <SettingsDialog />
    <RunSettingsDialog />
    <AppliedSettingsDialog />
    <RenameDialog />
    <ConfirmDialog />
    <ProcessingStatus />
</div>
