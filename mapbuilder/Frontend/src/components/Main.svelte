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
</script>

<div>
    <AppBar />
    <Toolbar />
    <AddMapDialog />
    <RenameDialog />
    <ConfirmDialog />
    <ProcessingStatus />
</div>
