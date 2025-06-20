<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Button } from "$lib/components/ui/button";
    import * as Dialog from "$lib/components/ui/dialog";
    import { appStore } from "../stores";

    const onOpenChange = (isOpen: boolean) => {
        appStore.setConfirmDialogVisible(isOpen);
    };
</script>

<Dialog.Root
    closeOnOutsideClick={true}
    bind:open={$appStore.confirmDialog.visible}
    {onOpenChange}
    closeOnEscape={false}
>
    <Dialog.Content class="sm:max-w-[425px]">
        <Dialog.Header>
            <Dialog.Title>Confirm</Dialog.Title>
        </Dialog.Header>
        {$appStore.confirmDialog.message}
        <Dialog.Footer>
            <Button
                on:click={() => onOpenChange(false)}
                variant="outline"
                disabled={$appStore.confirmDialog.spinning}>Cancel</Button
            >
            <Button
                type="submit"
                on:click={$appStore.confirmDialog.callback}
                variant="destructive"
                disabled={$appStore.confirmDialog.spinning}
            >
                {$appStore.confirmDialog.spinning ? "Working..." : "OK"}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
</style>
