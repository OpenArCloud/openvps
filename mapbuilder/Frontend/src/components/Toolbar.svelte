<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Button } from "$lib/components/ui/button";
    import * as Tooltip from "$lib/components/ui/tooltip";
    import { appStore } from "../stores";
    import UploadSvg from "../svg/uploadCloud.svelte";

    const onAddClick = () => {
        appStore.setAddDialogVisible(!$appStore.addDialogVisible);
    };
</script>

<div>
    <Tooltip.Root>
        <Tooltip.Trigger asChild let:builder>
            <Button builders={[builder]} variant="outline" size="icon" on:click={onAddClick}>
                <UploadSvg />
            </Button>
        </Tooltip.Trigger>
        <Tooltip.Content>Upload New Map</Tooltip.Content>
    </Tooltip.Root>
</div>

<style lang="postcss">
    div {
        width: 100%;
        background-color: theme(colors.secondary.DEFAULT);
        border-width: 0 0 1px;
        padding: 4px 12px;
        display: flex;
        justify-content: flex-end;
        stroke: theme("colors.secondary.foreground");
    }
</style>
