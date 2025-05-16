<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script>
    export let src = "";
    export let width = 64;
</script>

<div class="root">
    <img src={src+"?t="+Date.now()} {width} alt="thumbnail"  />
</div>

<style>
    .root img {
        margin: auto;
    }
</style>
