# Frontend toolchain

**bun + oxlint + oxfmt.** They own everything they can parse. One config per tool, at this directory,
discovered automatically — no package names a config path.

| Surface | Lint | Format | Type-check |
| --- | --- | --- | --- |
| `.ts` `.js` `.mjs` (incl. `*.svelte.ts`) | **oxlint** | **oxfmt** | `tsgo` (TypeScript 7) on pure-TS packages |
| `.json` `.md` `.css` `.html` `.yaml` | — | **oxfmt** | — |
| `.svelte` | ESLint + `eslint-plugin-svelte` | Prettier + `prettier-plugin-svelte` | `svelte-check` (TypeScript 6) |

Prettier's entire remaining job is `.svelte`. ESLint's entire remaining job is `.svelte` and
`*.svelte.ts`. Everything else — including the `.json`/`.md`/`.css`/`.html`/`.yaml` Prettier used to
own — is oxfmt's.

## Config: one file per tool, never named by a package

`.oxlintrc.json` and `.oxfmtrc.json` live here and **nowhere else**. Both tools resolve the nearest
config upward from the working directory, so every package's scripts are byte-identical:

```jsonc
"lint":      "oxlint .",
"fmt":       "oxfmt .",
"fmt:check": "oxfmt --check .",
```

No `--config ../../..`, no `--ignore-path`, no per-depth relative paths. Ignore globs live *inside*
each config for the same reason.

Prettier is the exception that proves it. Its *config* resolves upward like the others (the `prettier`
block in the root `package.json`), but its *ignore file* is read from the working directory only — and
every package invokes it from its own. A root `.prettierignore` therefore protected nothing, which is
how `.svelte-kit/generated/root.svelte`, a file SvelteKit writes, ended up failing `fmt:check`. So the
ignore is the glob: prettier is pointed at **`src/**/*.svelte`**, where every hand-written component
lives, and cannot reach build output from any directory. The `.prettierignore` is deleted rather than
left to look load-bearing, and `@repo/zone-contract` fails if a package widens the glob back.

This is not theoretical hygiene. `components/frontends/media` shipped its own `.oxfmtrc.json` and
`.oxlintrc.json`, inherited from the standalone lance-media repo. They sat dormant while nothing
invoked the oxc tools — and the moment oxlint and oxfmt were switched on they silently won, because
*nearest config wins*. That zone got 80-column double-quoted output against the root's 100-column
tabbed style, a different plugin set (`typescript` + `oxc`), `suspicious: warn`, and two rules
disabled. Nothing reported it; `svelte.config.js` just quietly reformatted. Both files are deleted,
and `@repo/zone-contract` now fails if a per-package `.oxlintrc.json`, `.oxfmtrc.json`, `.prettierrc`
or `eslint.config.js` reappears. A per-package config has to be a deliberate act, not a leftover.

## Why ESLint and Prettier are still here

Capability, not preference. Measured against **oxlint 1.75.0 / oxfmt 0.60.0**:

**oxfmt does not format `.svelte` — and fails open.** A deliberately mangled component
(`const   x   =    {a:1,b:2}`, unindented markup) passes `oxfmt --check` with *"All matched files use
the correct format"*, and `oxfmt --write` leaves it byte-identical. Point it at a directory containing
only a `.svelte` file and it reports *"Expected at least one target file"* — the extension is not a
target type. Dropping Prettier today would leave **268 components / 36k lines — 58% of the source** —
unformatted, with a green CI saying otherwise. That failure mode is worse than no formatter.

**oxlint cannot see a Svelte template, and reports false positives because of it.** On
`components/frontends/annotator/src/lib/viewer/PixiCanvas.svelte`:

```
error eslint(no-unassigned-vars): 'containerEl' is always 'undefined' because it's never assigned.
```

`containerEl` is assigned on line 141 by `bind:this={containerEl}`. oxlint reads the `<script>` block
and not the markup. `.svelte` is in its `ignorePatterns`; a half-parsed component is worse than an
unparsed one.

**The load-bearing rule is a template rule.** `eslint-rules/cross-zone-reload.js` asserts that an `<a>`
into another zone carries `data-sveltekit-reload`. Without it a cross-zone link soft-navigates into a
route manifest that does not contain the target — a 404 no type-check or unit test catches. It walks
the Svelte markup AST. Until that can run under oxlint, ESLint is enforcing a zone boundary, not a
style preference.

## rsvelte — evaluated, not adopted (yet)

[rsvelte](https://github.com/baseballyama/rsvelte) is the missing half: a Rust port of the Svelte 5
compiler built for oxc, shipping `@rsvelte/fmt`, `@rsvelte/oxlint-plugin` and `@rsvelte/svelte-check`.
It is the intended exit from this file. Tested against **this repo**, at `fmt@0.7.2`,
`oxlint-plugin@0.2.2`, `svelte-check@0.5.1`:

- **`rsvelte-fmt` works and is a strict oxfmt superset** — it formats `.svelte` in-process and
  delegates every other extension to oxfmt, so it would replace *both* oxfmt and Prettier with one
  binary and one `.oxfmtrc.json`. **Blocker:** it reformats 24 of 60 sampled components, and the
  change is a regression — a multi-line expression inside a markup attribute loses its indentation:

  ```svelte
  class={cn(
  	'…',            →   class={cn(
  	className,          '…',
  )}                     className,
                       )}
  ```

- **`@rsvelte/oxlint-plugin` works.** Enabled on `packages/ui` and `components/frontends/data` it
  produced real diagnostics (`svelte/no-unused-class-name`, a11y, compiler validator) inside the
  single oxlint pass. Documented alpha limits: scriptless components are skipped entirely, markup
  positions are approximate (reported at the top of `<script>`, true location in the message text),
  and there is no autofix.

- **`@rsvelte/svelte-check` is the one that would unblock TypeScript 7** — it takes `--tsgo`. But it
  **breaks on this codebase, fail-open**: it emits invalid TSX for
  `packages/ui/src/lib/components/data-table/data-table.svelte`, and the resulting syntax error
  makes TypeScript *suppress all semantic diagnostics program-wide*. Its own output says so:
  *"TypeScript suppressed all semantic (type) diagnostics program-wide … real type errors elsewhere
  may be hidden."* A type gate that silently stops checking is the worst possible outcome; upstream
  asks for a bug report.

All three are pre-1.0 — *"APIs and behaviour may change without notice. Use in production at your own
risk."* Re-run these three checks on each release; the moment `rsvelte-fmt`'s attribute indentation is
fixed, Prettier goes, and the moment `rsvelte-check --tsgo` type-checks this repo cleanly, both
`svelte-check` and `typescript@6` go with it.

## TypeScript 7

`typescript@7` is the native Go compiler: platform binaries, `tsc.js`, `getExePath.js`, and **no
JavaScript compiler API**. `svelte-check` calls `ts.sys.useCaseSensitiveFileNames` and dies instantly:

```
TypeError: Cannot read properties of undefined (reading 'useCaseSensitiveFileNames')
```

So TypeScript 7 cannot be the `typescript` dependency while `svelte-check` is in the toolchain:

- `typescript@6.0.3` — resolved by `svelte-check`, which owns `.svelte`.
- `@typescript/native-preview` (`tsgo` — the TS 7 engine under a second package name so both install)
  — the `check:tsgo` task, over every package whose sources are pure TypeScript: `@repo/api`,
  `@repo/engine`, `@repo/labeling`, `@repo/media-api`, `@repo/zone-contract`, plus media's core.

`tsgo` cannot resolve `*.svelte` imports either, so it could not own the component surface even if
`svelte-check` were gone. **Every line of TypeScript that TypeScript 7 can check, it checks.** The
remaining gap is `.svelte`, and `rsvelte-check --tsgo` is the only thing that closes it.

## The exit condition

Delete this file when `rsvelte-fmt` formats this repo's components without the indentation regression
and `@rsvelte/oxlint-plugin` can host `cross-zone-reload`. That removes `prettier`,
`prettier-plugin-svelte`, `prettier-plugin-tailwindcss`, `eslint`, `eslint-config-prettier`,
`eslint-plugin-svelte`, `typescript-eslint` and `eslint.config.js`. When `rsvelte-check --tsgo` also
runs clean, `svelte-check` and `typescript` follow, and `check` / `check:tsgo` collapse into one task.
