/**
 * Copyright 2025 Nokia
 * Licensed under the MIT License.
 * SPDX-License-Identifier: MIT
 */

import js from '@eslint/js';
import globals from 'globals';
import svelte from 'eslint-plugin-svelte';
import tseslint from 'typescript-eslint';
import importQuotes from 'eslint-plugin-import-quotes';

export default tseslint.config(
	js.configs.recommended,
	...tseslint.configs.recommended,
	...svelte.configs['flat/recommended'],
	{
		ignores: ['src/lib/*'],
	},
	{
		languageOptions: {
			ecmaVersion: 2018,
			sourceType: 'module',
			globals: {
				...globals.browser,
				...globals.es2021,
			},
		},
		plugins: {
			'import-quotes': importQuotes,
		},
		rules: {
			'array-bracket-spacing': ['error', 'never'],
			'block-spacing': ['error', 'always'],
			'brace-style': ['error', '1tbs', { allowSingleLine: true }],
			'comma-spacing': ['error', { before: false, after: true }],
			'comma-style': ['error', 'last'],
			'computed-property-spacing': ['error', 'never'],
			'eol-last': ['error', 'always'],
			eqeqeq: ['error', 'always', { null: 'ignore' }],
			'func-call-spacing': ['error', 'never'],
			'import-quotes/import-quotes': ['error', 'single'],
			indent: ['error', 'tab', { SwitchCase: 1 }],
			'key-spacing': ['error', { beforeColon: false, afterColon: true }],
			'keyword-spacing': ['error', { before: true, after: true }],
			'linebreak-style': ['error', 'unix'],
			'new-parens': ['error', 'always'],
			'no-mixed-spaces-and-tabs': 'error',
			'no-multi-spaces': ['error', { ignoreEOLComments: true }],
			'no-nested-ternary': 'error',
			'no-trailing-spaces': 'error',
			'no-unneeded-ternary': 'error',
			'no-unused-vars': 'off',
			'@typescript-eslint/no-unused-vars': 'error',
			'no-whitespace-before-property': 'error',
			'object-curly-spacing': ['error', 'always'],
			semi: ['error', 'always'],
			'semi-spacing': ['error', { before: false, after: true }],
			'semi-style': ['error', 'last'],
			'space-in-parens': ['error', 'never'],
			'space-infix-ops': 'error',
			'space-unary-ops': ['error', { words: false, nonwords: false }],
			'switch-colon-spacing': ['error', { before: false, after: true }],
			'template-curly-spacing': ['error', 'always'],
			'prefer-const': 'error',
		},
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parserOptions: {
				parser: tseslint.parser,
			},
		},
	},
);