/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import daisyui from "daisyui";

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
      },
    },
  },
  plugins: [daisyui],
  daisyui: {
    themes: [
      {
        emerald: {
          ...require("daisyui/src/theming/themes")["emerald"],
          "--rounded-btn": "0.5rem",
          "--rounded-box": "0.5rem",
        },
      },
      {
        forest: {
          ...require("daisyui/src/theming/themes")["forest"],
          "--rounded-btn": "0.5rem",
          "--rounded-box": "0.5rem",
        },
      },
    ],
    darkTheme: "forest",
  },
};
