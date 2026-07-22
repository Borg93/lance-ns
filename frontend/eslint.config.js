import path from 'node:path';
import { includeIgnoreFile } from '@eslint/compat';
import prettier from 'eslint-config-prettier';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import homeSvelteConfig from './components/frontends/home/svelte.config.js';
import dataSvelteConfig from './components/frontends/data/svelte.config.js';
import lineageSvelteConfig from './components/frontends/lineage/svelte.config.js';
import modelsSvelteConfig from './components/frontends/models/svelte.config.js';
import adminSvelteConfig from './components/frontends/admin/svelte.config.js';
import uiSvelteConfig from './packages/rask-ui/svelte.config.js';
// Local cross-zone-reload rule lives in its own module so its zone-matching logic is
// unit-tested (eslint-rules/cross-zone-reload.test.js).
import { raLocal } from './eslint-rules/cross-zone-reload.js';

const gitignorePath = path.resolve(import.meta.dirname, '.gitignore');

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	// eslint/prettier govern ONLY the rask-style MFE dirs; the remaining lance side
	// (packages/ui=@lance/ui, packages/config) is owned by oxlint/oxfmt — never traverse it.
	{
		ignores: [
			'packages/ui/',
			'packages/config/',
			'**/.svelte-kit/',
			'**/build/',
			'**/dist/',
			'**/*.generated.ts',
			'storybook-static/',
		],
	},
	ts.configs.recommended,
	svelte.configs.recommended,
	prettier,
	svelte.configs.prettier,
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node },
		},
		rules: {
			// typescript-eslint owns this; the base rule false-positives in TS projects.
			'no-undef': 'off',
			'@typescript-eslint/no-explicit-any': 'warn',
			// `interface Locals extends AuthLocals {}` (each zone's app.d.ts augments App.Locals from the
			// shared @rask/api seam) is the idiomatic SvelteKit pattern — allow a single-extends empty interface.
			'@typescript-eslint/no-empty-object-type': ['error', { allowInterfaces: 'with-single-extends' }],
			'@typescript-eslint/no-unused-vars': [
				'error',
				{
					argsIgnorePattern: '^_',
					varsIgnorePattern: '^_',
					caughtErrorsIgnorePattern: '^_',
				},
			],
			'svelte/prefer-svelte-reactivity': 'off',
			// GATE: keyless {#each} silently re-renders/reorders DOM on mutation.
			'svelte/require-each-key': 'error',
			'svelte/no-reactive-reassign': 'error',
			'svelte/no-navigation-without-resolve': 'off',
		},
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		rules: {
			// $effect() blocks are expressions, not assignments — expected Svelte 5 usage.
			'@typescript-eslint/no-unused-expressions': 'off',
		},
	},
	...[
		['home', homeSvelteConfig],
		['data', dataSvelteConfig],
		['lineage', lineageSvelteConfig],
		['models', modelsSvelteConfig],
		['admin', adminSvelteConfig],
	].map(([zone, cfg]) => ({
		files: [`components/frontends/${zone}/**/*.svelte`, `components/frontends/${zone}/**/*.svelte.ts`],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig: cfg,
			},
		},
	})),
	{
		files: ['packages/rask-ui/**/*.svelte', 'packages/rask-ui/**/*.svelte.ts'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig: uiSvelteConfig,
			},
		},
	},
	{
		// GATE: cross-zone <a> links must hard-navigate.
		files: ['components/frontends/**/*.svelte'],
		plugins: { 'ra-local': raLocal },
		rules: { 'ra-local/cross-zone-reload': 'error' },
	},
);
