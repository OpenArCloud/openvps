/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

// @ts-check

import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
    eslint.configs.recommended,
    ...tseslint.configs.recommended,
    {
        // config with just ignores is the replacement for `.eslintignore`
        ignores: ['**/dist/**', 'jest.config.js', '**/.idea/**'],
    },
);
