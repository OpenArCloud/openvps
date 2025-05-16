<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import * as Card from "$lib/components/ui/card";
    import { Button } from "$lib/components/ui/button";
    import { Label } from "$lib/components/ui/label";
    import { Input } from "$lib/components/ui/input";
    import { authenticate, type AuthenticationResult } from "../auth";
    import LoadingIndicator from "./LoadingIndicator.svelte";
    import { push as gotoRoute } from "svelte-spa-router";

    let userId: string = "";
    let password: string = "";
    let isLoading: boolean = false;
    let error: string = "";

    $: isLoginEnabled = userId && password;

    async function login() {
        if (!isLoginEnabled) {
            return;
        }

        error = "";
        isLoading = true;
        const result: AuthenticationResult = await authenticate(userId, password).catch(
            (reject: AuthenticationResult) => {
                return reject;
            },
        );
        isLoading = false;

        if (result.success) {
            gotoRoute("/");
        } else {
            error = result.message;
        }
    }
</script>

<div class="root">
    <header>Map Builder</header>
    <Card.Root class="w-[480px] relative">
        {#if isLoading}
            <LoadingIndicator />
        {/if}
        <Card.Header>
            <Card.Title>Login</Card.Title>
        </Card.Header>
        <Card.Content>
            <form on:submit|preventDefault={login}>
                <Label>User ID</Label>
                <Input
                    bind:value={userId}
                    class="{'userId'},"
                    required
                    minlength={4}
                    maxlength={20}
                    pattern="^[a-zA-Z0-9_]*$"
                    readonly={isLoading}
                    autocomplete="username"
                    on:keypress={(e) => e.key === "Enter" && login()}
                />
                <br />
                <Label>Password</Label>
                <Input
                    type="password"
                    bind:value={password}
                    required
                    autocomplete="current-password"
                    readonly={isLoading}
                    on:keypress={(e) => e.key === "Enter" && login()}
                />
                {#if error}
                    <div class="error">
                        {error}
                    </div>
                {/if}
            </form>
        </Card.Content>
        <Card.Footer class="flex-row justify-end">
            <Button disabled={!isLoginEnabled || isLoading} on:click={login}>Login</Button>
        </Card.Footer>
    </Card.Root>
    <footer>v0.01</footer>
</div>

<style lang="postcss">
    .root {
        font-family: Helvetica, Arial, sans-serif;
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        height: 100%;
    }

    header {
        font-size: 3rem;
        font-weight: bold;
        text-align: center;
        margin: 50px;
        text-shadow:
            theme(colors.primary.DEFAULT) 50px 0 50px,
            theme(colors.primary.DEFAULT) -50px 0 50px;
    }

    footer {
        width: 100%;
        font-size: 1rem;
        position: absolute;
        text-align: right;
        bottom: 0;
        padding: 4px 12px;
    }

    .error {
        color: theme(colors.red.500);
        margin-top: 12px;
        font-size: 0.8em;
    }
</style>
