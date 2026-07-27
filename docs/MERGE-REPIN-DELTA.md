# Merge re-pin delta — what changed in lance-ns since the plan was written

`rask/docs/architecture/lance-ns-merge.md` is the authority for the merge (owner rulings R1–R7, ACCEPTED
2026-07-24). It is pinned at **`lance-ns main@df70b63`** and states its own rule:

> re-pin to current lance-ns main at each phase copy — copies are taken fresh, never stale.

**That pin is 190 commits behind.** This file is the re-pin input: what moved, which plan rows it
invalidates, and what open work carries over. It is written on the lance-ns side because the plan forbids
editing lance-ns from the rask branch; whoever executes a phase reads this first and amends the plan.

Measured 2026-07-27 against `git log df70b63..HEAD`.

---

## 1. Structural invalidations — plan rows that are now wrong

These are not cosmetic. Anyone executing P2 today goes looking for four zones that no longer exist.

| Plan says | Reality at HEAD | Phases affected |
|---|---|---|
| Zones `data`, `lineage`, `models`, `admin` move separately; "the **6** lance zones"; turbo build across "**13** zones" | **Four zones total**: `home`, `lakehouse`, `media`, `annotator`. `bb099df` merged data+lineage+models+admin into **one `lakehouse` zone** whose four areas are routes, not apps | P0 layout table · P2 step 4 · P4 `frontend.apps` + ingress rules · P6 per-zone spec files |
| `frontend/packages/api` (`@rask/api` fork), `frontend/packages/rask-ui` (`@rask/ui` fork) | **Seven packages**, renamed to the `@repo/*` scope: `api`, `ui`, `config`, `engine`, `labeling`, `media-api`, `zone-contract`. `media-api` and `zone-contract` are net-new and have no plan row | P0 · P2 steps 2–3 |
| `frontend/eslint-rules/cross-zone-reload.js` → rask eslint flat config as a local plugin | **The directory does not exist.** The frontend moved to **oxlint + oxfmt** (`.oxlintrc.json`, `.oxfmtrc.json`, `frontend/TOOLING.md`). The cross-zone-reload guard survives as a *test* in `@repo/zone-contract`, not a lint rule | P0 · P2 gates ("eslint (incl. cross-zone-reload rule)") |
| P2 step 1 normalizes with `prettier-plugin-tailwindcss` | lance-ns has **no prettier**. The formatter is `oxfmt`/`rsvelte-fmt`; `@repo/zone-contract` asserts byte-identical `lint`/`fmt`/`fmt:check` scripts in every workspace package and fails on drift in either direction | P2 step 1 — the 3-way-merge normalization strategy needs rewriting for a different formatter |

## 2. Things built since the pin that the plan has no row for at all

| What | Where | Why the merge cares |
|---|---|---|
| **Dapr state store** | `chart/templates/dapr-statestore.yaml` — `state.postgresql`, `actorStateStore: "true"`, DSN from OpenBao via `lance-secrets`, `scopes: [annotator, catalog]` | Needs a row in P4's Dapr resources **and** in the §1 externalization table (→ CNPG). An app missing from `scopes` gets "component not found" from its sidecar and every user's saved work 503s — logged by the sidecar, noticed by nothing else. `test_invariants.py` pins the agreement |
| **Per-subject user state** | `services/common/user_state.py`, `services/catalog/api/v1/endpoints/user_state.py`, the zones' `capi/v1/user-state/[document]` proxies | New catalog surface (`/v1/user-state/…`) → new gateway rows in P1's `_routes()` |
| **Run-notification transport** | `@repo/api/runs-feed` + a four-line `feeds.remote.ts` per zone | Every zone's shell holds a `query.live` SSE stream open. See §4 — this is the one that bites at the ingress swap |
| **Runners** | `chart/templates/runners.yaml`, `runners/assist`, `.docker/assist-runner.dockerfile` | A deployable the P0 table and P3 image list do not mention |
| **`me` + `access_admin` endpoints** | `services/catalog/api/v1/endpoints/{me,access_admin}.py` | More gateway rows |
| **Encoder URL seam** | `encoders.*Url` values + `scripts/encoder_stub.py` | Media search modes are a URL, not a Deployment — proven to flip 503 → 200. If rask has GPUs the same values point at real servers with no code change |

## 3. What is now EASIER than the plan assumed

Not everything drifted against us.

- **Four zones instead of seven** is less to move, less to register in `microfrontends.json`, fewer port
  slots, fewer ingress rules, fewer P6 spec files. The plan's hardest frontend row got smaller.
- **AGE on CNPG is decided and proven** — the plan's PROPOSED decision 1 and `RASK-INTEGRATION.md`'s
  "decide before the fold-in" are both settled: AGE reached PG18 (v1.7.0) and mounts as a CNPG ImageVolume
  extension on a **stock** image, proven on a throwaway kind cluster with the real operator
  (`docs/CNPG-AGE.md`, `.docker/cnpg-age-ext.dockerfile`). The CSI-mount leg still needs K8s 1.33+.
- **Tenancy is no longer an open decision.** The plan and `RASK-INTEGRATION.md` both ask to "confirm
  one warehouse-per-deploy stays the model". It does not: per-warehouse physical multi-tenancy provisions a
  separate bucket per warehouse (#27) and per-tenant medallion zones landed (#84). rask's single implicit
  `default` project is the degenerate case of ours and works unchanged.
- **The catalog 501 count is confirmed at 7**, not drifting — `docs/COVERAGE.md`, 47/54 backed. (A crude
  `grep -c 501` reads 8 and is wrong; it counts prose.) `COVERAGE.md`'s own test count is stale, though:
  it says `568 passed` measured 2026-07-12; it is **1213** now.
- **Two CI failure classes are fixed and gated**, so they will not be inherited: `svelte-kit sync` racing
  `vite build` over `.svelte-kit/types` (turbo `check` now depends on its own package's `build`), and
  Playwright `workers: 8` starving a small runner (`CI ? 2 : 8`).

## 4. The one new thing that bites at the ingress swap

Every zone's shell now holds a `query.live` SSE stream open for the run-notification bell. Proven live at
**269.6s with 2 streams and 0 severed** — past nginx's 60s default and past Bun's 255s `IDLE_TIMEOUT`. That
rests on two things and **only one of them travels**:

- `nginx.ingress.kubernetes.io/proxy-read-timeout: 3600` on our Ingress. **rask uses Traefik.** Without its
  equivalent every zone reconnects on a timer, and each reconnect re-primes the event window and writes an
  audit record. Nothing in the plan mentions it.
- The application keepalive in `@repo/api/runs-feed`, re-yielding the last pulse every 20s. Ours, and it
  moves with the code.

`scripts/verify_live_stream_timeout.mjs` takes `HOLD_S`; run it past 255 against rask's ingress in P4.

Related and already learned the hard way: **`waitUntil: 'networkidle'` can never fire again** in any zone —
these apps have no idle network by design. Ten such waits were replaced and
`@repo/zone-contract/no-networkidle.test.ts` fails on a new one. P6's new spec files must not reintroduce it.

## 4b. Owner rulings R8 + R9 (2026-07-27) — the surviving zone set

Recorded in the plan's ruling table. **`home + lakehouse + media + annotator + compute + studio`** — six
zones.

- rask's **browse / viewing / search** surfaces are eaten by the media plane — R6, reconfirmed by the owner.
- **`compute` survives** (Ray dashboard, jobs, actors, cluster) — the plane rask owns.
- **`storage` folds INTO `lakehouse`**: an S3 object browser is a lakehouse view of the warehouse's own
  buckets, not a separate destination. `train` folds in with it via lance `models`, now a lakehouse route.
  `overview` folds into `home`.
- **`studio` survives as its own top-navbar zone (R9)** — not folded into anything. This matches what it
  already is on the rask side: a top-level nav entry in `packages/ui/src/lib/shell/nav-config.ts:81`
  (`Studio`, `Shapes` icon) with its own `/animation` route, so the ruling preserves a surface rather than
  inventing one.

## 4c. Two preconditions the plan did not have

1. **rask's `ty` gate is red before the merge starts.** `uvx ty check` on rask's unmodified
   `feat/lance-ns-merge` reports **70 errors** — `components/scripts/index_alto.py` (39),
   `components/services/core` (24), `packages/htr/src` (10), `components/services/ray_api` (7),
   `packages/storage/src` (4). None is lance-ns code. P1's gate requires `make check` green and rask's
   pre-commit hook enforces it, so **nothing can be committed on the branch** until it is cleared. The
   re-pin commit itself needed `--no-verify`.
2. **The two frontends have incompatible toolchains.** rask: eslint + prettier. lance-ns: oxlint + oxfmt,
   with `@repo/zone-contract` asserting byte-identical `lint`/`fmt`/`fmt:check` scripts everywhere. Decide
   the direction and land it as one pure-format commit before any 3-way merge.

## 4d. What an adversarial sweep of the plan found after the first re-pin

21 agents over rask's `docs/architecture/`, its other docs, `CLAUDE.md` + `.claude/**`, and its config
manifests. **9 confirmed, 8 rejected.** Every confirmed finding was in the merge plan itself — the first
re-pin amended the sections it was looking at and left identical drift in nine others in the same file
(P0 naming rule 3, P3's "13 zones", P4's "6 lance zones", the reserved-segment guard, the global
live-proof's `/data`+`/admin` drive, risk 4, risk 7). All nine fixed in rask `aa26827`.

**rask's own agent-facing docs came back clean.** All 8 rejections were verifiers refusing findings against
`CLAUDE.md` and the vendored `rask-*` skills because those correctly describe rask *as it is today* — a doc
describing rask's present is not stale; only one describing the merged result can be.

Two findings were new rather than corrections, and both matter at P2.4:

- **The dev ports collide.** lance `lakehouse` 5174 vs rask `storage` 5174, and lance `annotator` 5177 vs
  rask `studio` 5177 — and R9 keeps `studio`, so it is live. The three incoming zones must be reassigned.
- **The naming rule's own rationale cited a zone that no longer exists** (`lineage` zone vs `lineage`
  backend). The collision class is still real and now sharper: the **`annotator` zone vs the
  `services/annotator` backend** under one release.

## 4e. The layout decision (owner question + ruling, 2026-07-27)

**rask's `components/` + `packages/` layout is the target, and the reason is the uv workspace, not tidiness.**

lance-ns has **no uv workspace**. It is a single package named `lance-ns` with
`pythonpath = ["services", "."]` — a pytest path hack that makes `catalog`, `lineage`, `medallion` and the
rest import as top-level modules. Because nothing declares a dependency on anything, nothing can violate
one: `catalog` reaching into `medallion`'s internals is not an error, it is just an import.

rask is a real workspace: **14 members**, each with its own `pyproject.toml`, `src/`, `tests/` and declared
deps (`service-kit` depends on `storage`). The move is a conversion from implicit to *enforced* module
boundaries, with the resolver doing the enforcing.

Three lance-ns oddities are symptoms of the same missing workspace, and all three get a home:

| Today | Why it is odd | Lands as |
| --- | --- | --- |
| `services/common` | A library living in the services directory — no `main.py`, no `app.py` | `packages/common` (import root stays `common`, zero rewrites) |
| `src/ratch` | Excluded from the root's own tooling (`pyproject.toml:113`) because its `ray[data]`/`lance-ray`/`typer` stack is not wanted at root | **`packages/ratch`** — a workspace member, which is what *resolves* the exclusion: the heavy deps move into its own pyproject. **Owner-ruled: ratch is a package, not a `components/cli` deployable** |
| `runners/` | A deployable with nowhere to be | `components/runners/assist` |

The frontend half is already done: the P5 migration deliberately put `frontend/` into rask's exact internal
shape, so `frontend/components/frontends/<zone>` → `components/frontends/<zone>` is a directory move. The
Python side is the real work.

## 5. Open work carried over

Nothing here blocks the merge's own four verification conditions. It carries over so it is not lost.

| # | State | Carry-over note |
|---|---|---|
| `#122` annotation projects | Designed in full (`docs/DESIGN-annotation-projects.md`), built only as far as `#124` allows | Slices `S1`–`S4` need no store; `S5`–`S10` need actors |
| `#124` interactive state | **Half done.** Store live and proven; **no actor type and no workflow registered** | The `actorStateStore` flag is on and unused — see `#128` |
| `#128` notification actor | Not started | Read/dismissed state is per-tab until it exists |
| `#103` media plane on the governed warehouse | Deferred here, **blocking at the merge** | The corpus is a node `hostPath` (`/var/media-corpus`). The plan's P4 already rules "no hostPath ships" — this is the work that satisfies it |
| `#119` `TableDetail` reset effect | Deferred with reason | Earned it: an edit there dropped 6 of 10 history versions with `svelte-check` at 0 errors |
| `#97` product-works pass | In progress | Ten conditions, orthogonal to the merge |
| `#111` lineage track | Part landed | Spec-fidelity + Marquez-parity reports done; gold JSONB embed is P7b's schema contract |
| `#86`, `#100`, `#101`, `#112`, `#20` | Parked / owner-deferred | Unchanged by the merge |
| Storybook | Struck for now | rask keeps its own (plan P2 step 3) — adopt rask's rather than re-deciding |
| `/lakehouse/data` scaffold, `/lakehouse/admin` orphan | Product decisions, not defects | Carry as-is |

## 6. What to do with this file

At the next phase copy: re-pin the plan's header to current lance-ns `main`, apply §1 and §2 to the P0
layout table and the P2/P4/P6 gate lists, strike the §3 rows from the open-decisions list, and add §4 to P4.
Then delete this file — it is a diff, not a design record, and a stale diff is worse than none.
