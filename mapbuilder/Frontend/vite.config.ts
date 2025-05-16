/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [svelte()],
	server: {
		cors: {
			origin: "*",
		},
		port: 8047,
		proxy: {
			'/maps': 'http://localhost:3000',
			'/uploadStrayRecordingZip': 'http://localhost:3000',
			'/auth': {
				target: 'http://localhost:3000',
				changeOrigin: false,
			},
		}
	},
	resolve: {
		alias: {
			$lib: path.resolve("./src/lib"),
		},
	}
});
