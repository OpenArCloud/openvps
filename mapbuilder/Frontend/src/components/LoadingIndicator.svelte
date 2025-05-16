<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script>
    import { Circle } from "svelte-loading-spinners";
</script>

<div class="root">
    <Circle color="hsl(var(--primary))" />
</div>

<style>
    .root {
        position: absolute;
        top: 50%;
        left: 50%;
        margin: -30px -30px;
    }
</style>
