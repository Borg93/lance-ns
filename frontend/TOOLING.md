# Frontend toolchain — what owns what, and why

**The preference is bun + oxlint + oxfmt.** They own everything they can currently parse. ESLint and
Prettier remain only where the oxc toolchain cannot go yet, which today is exactly one thing: Svelte.

| Surface | Lint | Format | Type-check |
| --- | --- | --- | --- |
| `.ts` `.js` `.mjs` (incl. `*.svelte.ts`) | **oxlint** | **oxfmt** | `tsgo` (TypeScript 7) where sources are pure TS |
| `.svelte` | ESLint + `eslint-plugin-svelte` | Prettier + `prettier-plugin-svelte` | `svelte-check` (TypeScript 6) |
| `.css` `.md` `.json` `.html` | — | Prettier | — |

Everything runs through bun: `bun install`, `bunx turbo`, and every tool above is a root
devDependency. No globally installed binary, no second package manager, no `npx`. The Dagger CI
container pins `oven/bun:1.3.14-slim` by digest and `packageManager` pins `bun@1.3.14`, so CI and a
laptop run the same toolchain byte for byte.

## Why ESLint and Prettier are still here

Not preference — capability. Measured against oxlint 1.75.0 / oxfmt 0.60.0:

**oxfmt cannot parse `.svelte` at all.** `oxfmt --check` on a `.svelte` file reports
`Expected at least one target file. All matched files may have been excluded by ignore rules` — the
extension is not recognised. Experimental support landed upstream in
[oxc#21700](https://github.com/oxc-project/oxc/pull/21700) but is not in a released version.

**oxlint cannot see a Svelte template**, and silently produces false positives because of it. Run
against `components/frontends/annotator/src/lib/viewer/PixiCanvas.svelte` it reports:

```
error eslint(no-unassigned-vars): 'containerEl' is always 'undefined' because it's never assigned.
```

`containerEl` is assigned on line 141 by `bind:this={containerEl}`. oxlint reads the `<script>` block
and not the markup, so a template-assigned variable looks dead. `.svelte` is therefore in oxlint's
`ignorePatterns` — a partially-parsed component is worse than an unparsed one.

**The load-bearing rule is a template rule.** `eslint-rules/cross-zone-reload.js` asserts that an `<a>`
pointing at another zone carries `data-sveltekit-reload`. Without it a cross-zone link soft-navigates
into a route manifest that does not contain the target, and the app breaks in a way no type-check or
test catches. It inspects Svelte *markup*. Until oxlint parses templates and supports custom JS rules
against them, ESLint is not optional here — it is the only thing enforcing a zone boundary.

## What the split actually bought

- `oxlint` covers 362 `.ts/.js/.mjs` files in **~90 ms**. ESLint now only walks `.svelte`.
- `lint` and `fmt:check` are **package tasks**, so turbo parallelises and caches them. They used to be
  root tasks (`//#lint`, `//#fmt:check`) running once, repo-wide, uncached, over a hand-maintained list
  of 13 paths — which had already drifted (it never covered `.mjs`, so `components/frontends/media/e2e`
  was unformatted).
- Cold `turbo run lint` 55 s → warm, `33 ms` (`FULL TURBO`). Cold `fmt:check` is 8.9 s.

The migration was **rule-for-rule and byte-for-byte**, deliberately:

- `.oxfmtrc.json` mirrors the Prettier options the repo already used (`printWidth` 100, tabs, single
  quotes, trailing commas). Reformatting all 365 TS/JS files with oxfmt changed **4** of them, and all
  four are line-breaking choices (leading `|` on multi-line unions, arrow-callback wrapping).
- `.oxlintrc.json` pins `plugins: ["typescript"]`. oxlint enables `unicorn`/`oxc`/`import` by default
  and files several of their stylistic rules under `correctness` — `unicorn/no-new-array` alone fires
  9 times on the deliberate `new Array(n)` preallocation in the Pixi hot path. ESLint enforced core +
  typescript-eslint here; widening that is a separate, deliberate decision, not a migration artefact.

## TypeScript 7

`typescript@7` is the native (Go) compiler. It ships platform binaries, `tsc.js` and `getExePath.js` —
and **no JavaScript compiler API**. `svelte-check` calls `ts.sys.useCaseSensitiveFileNames`, so it dies
immediately against TS 7:

```
TypeError: Cannot read properties of undefined (reading 'useCaseSensitiveFileNames')
```

So TypeScript 7 cannot be the `typescript` dependency while svelte-check is in the toolchain. The split
is:

- `typescript@6.0.3` — resolved by `svelte-check`, which owns the `.svelte` surface.
- `@typescript/native-preview` (`tsgo`, the TS 7 engine under a different package name so both can be
  installed) — the `check:tsgo` task, run over every package whose sources are pure TypeScript:
  `@rask/api`, `@lance/engine`, `@lance/labeling`, `@lance/media-api`, `@rask/zone-contract`, and
  media's schema-agnostic core.

`tsgo` also cannot resolve `*.svelte` imports, so it could not own the zones' component surface even if
svelte-check were gone. **Every line of TypeScript that can be checked by TypeScript 7 is.**

## When to revisit

Delete this file and collapse to two tools when oxfmt ships non-experimental `.svelte` formatting and
oxlint parses Svelte templates with custom-rule support. At that point `eslint-plugin-svelte`,
`prettier-plugin-svelte`, `eslint`, `prettier`, `typescript-eslint` and `eslint.config.js` all go, and
`eslint-rules/cross-zone-reload.js` becomes an oxlint JS plugin. Separately, when
`svelte-language-tools` supports the TypeScript 7 API, `typescript` moves to 7 and `check`/`check:tsgo`
collapse into one task.
