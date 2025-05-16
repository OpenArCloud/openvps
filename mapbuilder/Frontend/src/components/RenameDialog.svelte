<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { Button } from "$lib/components/ui/button";
    import * as Dialog from "$lib/components/ui/dialog";
    import { Input } from "$lib/components/ui/input";
    import { appStore } from "../stores";

    const onOpenChange = (isOpen: boolean) => {
        appStore.setRenameDialogVisible(isOpen);
    };

    let mapName = "";
</script>

<Dialog.Root closeOnOutsideClick={true} bind:open={$appStore.renameDialog.visible} {onOpenChange}>
    <Dialog.Content class="sm:max-w-[425px]">
        <Dialog.Header>
            <Dialog.Title>Rename {$appStore.renameDialog.oldName}</Dialog.Title>
        </Dialog.Header>
        <Input type="text" placeholder="" class="max-w-xs" bind:value={mapName} />
        <Dialog.Footer>
            <Button on:click={() => onOpenChange(false)} variant="outline">Cancel</Button>
            <Button type="submit" on:click={() => $appStore.renameDialog.callback(mapName)}>OK</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
</style>
