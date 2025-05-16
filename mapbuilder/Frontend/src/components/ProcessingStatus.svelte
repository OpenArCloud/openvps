<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { processingStore, disconnectSocket, connectSocket, localizerStore } from "../stores";
    import { onMount } from "svelte";
    import ProcessingTable from "./ProcessingTable.svelte";
    import MessageDialog from "./MessageDialog.svelte";
    import LoadingIndicator from "./LoadingIndicator.svelte";

    onMount(() => {
        processingStore.fetch();
        localizerStore.fetch();
        connectSocket();
        return disconnectSocket;
    });
</script>

<div class="root">
    {#if $processingStore.error}
        <MessageDialog title="Error" message={String($processingStore.error)} />
    {:else if $processingStore.isLoading}
        <LoadingIndicator />
    {/if}
    <ProcessingTable />
</div>

<style lang="postcss">
    .root {
        flex: 1 0 50px;
        position: relative;
    }
</style>
