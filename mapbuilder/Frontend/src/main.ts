/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import "./app.css";
import App from "./components/App.svelte";

function handleThemeChange(e) {
    if (e.matches) {
        document.body.classList.add("dark");
        document.body.classList.remove("light");
    } else {
        document.body.classList.remove("dark");
        document.body.classList.add("light");
    }
}

const savedTheme: string | null = localStorage.getItem("theme");
if (savedTheme === "dark" || savedTheme === "light") {
    document.body.className = savedTheme;
} else {
    const prefersDarkScheme = window.matchMedia("(prefers-color-scheme: dark)");
    if (prefersDarkScheme.matches) {
        // User prefers dark theme
        document.body.classList.add("dark");
    } else {
        // User prefers light theme
        document.body.classList.add("light");
    }
    prefersDarkScheme.addEventListener("change", handleThemeChange);

    // Call the handler initially to set the theme correctly on page load
    handleThemeChange(prefersDarkScheme);
}

const app = new App({
    target: document.getElementById("app")!,
});

export default app;
