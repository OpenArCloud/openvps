<!--
 Copyright 2025 Nokia
 Licensed under the MIT License.
 SPDX-License-Identifier: MIT
-->

<script lang="ts">
    import "../app.css";
    import Router from "svelte-spa-router";
    import { wrap } from "svelte-spa-router/wrap";
    import InvalidRoute from "./InvalidRoute.svelte";
    import Main from "./Main.svelte";
    import Login from "./Login.svelte";
    import type { ComponentType } from "svelte";
    import { isAuthenticated } from "../auth";
    import { push as gotoRoute } from "svelte-spa-router";
    import { AUTH_ENABLED } from "../config.js";

    const getRouteComponent = (
        isProtected: boolean,
        compType: ComponentType,
    ): Promise<{ default: ComponentType }> => {
        if (!isProtected || !AUTH_ENABLED || isAuthenticated()) {
            return Promise.resolve({ default: compType });
        }
        gotoRoute("/login");
        return Promise.resolve({ default: Login });
    };

    const routes = {
        "/login": wrap({
            asyncComponent: () => getRouteComponent(false, Login),
        }),

        "/": wrap({
            asyncComponent: () => getRouteComponent(true, Main),
        }),

        "*": InvalidRoute,
    };
</script>

<main>
    <Router {routes} />
</main>

<style>
    main {
        display: flex;
        flex-direction: column;
        height: 100vh;
    }
</style>
