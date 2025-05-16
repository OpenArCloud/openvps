<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import { appStore } from "../stores";
    import * as Avatar from "$lib/components/ui/avatar";
    import * as DropdownMenu from "$lib/components/ui/dropdown-menu";

    if (localStorage.getItem("theme") === "light" || localStorage.getItem("theme") === "dark") {
        $appStore.setTheme(localStorage.getItem("theme") as "light" | "dark");
    }

    const getUserName = async () => {
        const session = await fetch("/auth/session").then((res) => res.json());
        const user = session.user.name || session.user.email || "unnamed";
        return user;
    };

    const getUserInitials = async () => {
        const user = await getUserName();
        if (!user) {
            return "?";
        }
        const names = user.split(" ");
        return names.map((name) => name[0].toUpperCase()).join("");
    };

    const onLogout = async () => {
        window.location.replace("/auth/signout");
    };

    let username = "";
    let initials = "";
    getUserName().then((result) => (username = result));
    getUserInitials().then((result) => (initials = result));
</script>

<div class="root">
    <div class="title">
        <p><image src="/OSCAR4US.jpg" alt="OSCAR4US logo" style="float:left;width:50px;height:50px;"/>
        OpenVPS MapBuilder
        </p>
    </div>
    <div class="controls">
        <DropdownMenu.Root>
            <DropdownMenu.Trigger>
                <Avatar.Root class="h-8 w-8">
                    <Avatar.Fallback>
                        {initials}
                    </Avatar.Fallback>
                </Avatar.Root>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content>
                <DropdownMenu.Group>
                    <DropdownMenu.Label>
                        <span class="menuLabel"> Logged in as </span>
                        <span class="userName">
                            {username}
                        </span>
                    </DropdownMenu.Label>
                    <DropdownMenu.Separator />
                    <DropdownMenu.Item on:click={onLogout}>Logout</DropdownMenu.Item>
                </DropdownMenu.Group>
            </DropdownMenu.Content>
        </DropdownMenu.Root>
    </div>
</div>

<style>
    .root {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
    }
    .title {
        font-family: Helvetica, Arial, sans-serif;
        font-size: 1.5em;
        padding: 12px 24px 12px 36px;
        border-width: 0 0 1px;
    }
    .controls {
        padding: 12px 24px;
        display: flex;
        align-items: center;
        column-gap: 12px;
        stroke: theme("colors.secondary.foreground");
    }

    .menuLabel {
        font-weight: normal;
    }

    .userName {
        font-weight: bold;
    }
</style>
