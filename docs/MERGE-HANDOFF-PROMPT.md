# Handoff prompt v3 — mend, then copy

Paste everything below the line into the rask session NOW. Part A closes the gaps an external audit found
in its live tree (2026-07-27); Part B is the copy phase it flows straight into.

---

You are continuing the lance-ns → rask merge on `/home/blackwell/Desktop/rask`, branch
`feat/lance-ns-merge`. The authority is `docs/architecture/lance-ns-merge.md` (rulings R1–R10, D7).

# PART A — mend the restructure first (externally audited 2026-07-27; verify each from the tree)

Your restructure is well underway and mostly right: `components/` dissolved, `services/` at root, root
`packages/` Python-only, uv members are globs, eslint+prettier deleted, the JS tooling moved into
`frontend/`. Five things are wrong or unfinished. Fix them in this order and commit as you go.

1. **Commit before you rebase — your step order inverted itself.** The branch sits **69 commits behind
   `origin/main`** with the entire restructure UNCOMMITTED (401 files: 360 R, 26 RM, 15 M, 4 D, 3 ??).
   Git cannot rebase a dirty tree, and rename detection works far better on committed renames. So:
   clear item 2, **commit the restructure as its own series**, THEN rebase onto `origin/main` and
   delete the orphaned `projects/controlplane` your earlier removal missed.
2. **`ty` is red at 88 diagnostics — and your pre-commit hook enforces it.** ~50 are the pre-existing set
   (`scripts/index_alto.py` 39, `services/core` 24, `packages/htr` 10, `services/ray_api` 7,
   `packages/storage` 4 — post-move paths) and **38 are in `.venv/`**, which means the ty config stopped
   excluding the virtualenv after the moves — fix the exclusion first, then clear the real ones. Do NOT
   `--no-verify` the restructure commit; if the gate is relaxed here it never comes back.
3. **The zone directory is OWNER-RULED (R11): `frontend/microfrontends/` is the shape. Keep it.** Record
   R11 in `docs/architecture/lance-ns-merge.md`'s ruling table. The consequence lands at COPY time, not
   now: the incoming lance-ns frontend encodes `components/frontends/` and must be adapted to
   `microfrontends/` **in the same commit as the copy**, with the full gate suite re-run. The measured
   patch surface (from the source tree, node_modules excluded) is exactly:
   `frontend/package.json` (the workspaces glob) · `frontend/turbo.json` (1 ref) · the four zones'
   `vite.config.ts` (1 each) · `packages/media-api/src/api.ts` (1) · and **14 files in
   `packages/zone-contract/src/`** (manifest.ts carries 9 refs incl. the literal read of
   `components/frontends/home/microfrontends.json`; the rest 1–4 each). It is a mechanical
   find-and-replace of one path segment, and `@repo/zone-contract`'s own manifest tests then verify the
   result — if the rename is incomplete, the suite fails rather than silently passing. Your current
   2-file `zone-contract` stub is REPLACED by the full incoming package (10 test files, 591 tests) as
   part of the same commit.
4. **`runners/` does not exist and `services/runner` is still a workspace member** carrying
   `ray[data,default,serve]>=2.52,<2.56` inside the fleet's resolution — against the ABSOLUTE rule (a
   runner is NEVER a member; no "resolves-today" exception). `git mv services/runner runners/htr`; it
   keeps its own `pyproject.toml`, gains its own `uv.lock` (`cd runners/htr && uv lock`), and is matched
   by no members glob. Re-run `uv lock` at root after — the fleet's resolution must shrink, not grow.
5. **Strays:** `batches.db.20260527T105358Z` still at the root (your own step-1 list deletes it).
   `frontend/packages/{api,ui}` are still `@rask/api`/`@rask/ui` — fine for now, they fold into `@repo/*`
   at copy; just don't add new imports of those names.

**Part A gates before proceeding:** clean `git status`; rebased on `origin/main`; `uvx ty check` clean;
`uv sync` clean; `bun install` + `turbo run build` green from `frontend/`; helm lint green. Report an
honest fraction, then continue below.

# PART B — the copy: lance-ns in, ALL of it (R1, total merge)

**Source pin: `/home/blackwell/Desktop/lance-ns` at current `main` (`378970d` at authoring; docs-only
since `f8df8de` — re-pin to `git -C /home/blackwell/Desktop/lance-ns rev-parse main` at copy time; copies
are taken fresh, never stale).** Never edit that repo — copy out only. Never push rask to any remote;
never commit to or merge with rask `main`. **Copy-completeness gate:** after copying, diff the top-level
inventory — every item in `git -C …/lance-ns ls-files | cut -d/ -f1 | sort -u` (28 today) must exist in
the rask tree or appear in your commit message with the manifest row that transformed it. Nothing from
lance-ns is dropped silently.

## The zone set — who survives, who is eaten, who owns the top navbar (R6 + R8 + R9)

Six zones, all six in the top navbar: **`home · lakehouse · media · annotator · compute · studio`**.

- **rask's viewing / browse / search estate is EATEN by the lance-ns media plane.** The `discover` zone
  (browse + search), the EAD `/api/v1/catalog` endpoints, `search_api`, and `volumes_api`'s page/ALTO
  viewing all retire; lance-ns `viewer`/`search`/`annotator` services and the `media` + `annotator` zones
  replace them. What survives of `volumes_api` is only the `/objects` S3 browser — re-landing as a view
  *inside* `lakehouse`, not a zone.
- **`compute` survives as its own top-navbar zone** — Ray dashboard, jobs, actors, cluster. The plane rask
  owns.
- **`studio` survives as its own top-navbar zone** (R9) — not folded into anything; it already is one
  (`nav-config.ts`, its own `/animation` route).
- `storage` folds INTO `lakehouse`; `train` folds in via `models` (a lakehouse route); `overview` folds
  into `home`. One home: rask's home content folds into the incoming `home` zone, which owns
  `/auth/{login,callback,logout}` and the catch-all.

## Before copying — verify your own step 2, from the tree, not from memory

1. `frontend/` exists; `components/` is gone; `eslint.config.js` and every prettier config are deleted
   (R10 — oxlint + oxfmt + rsvelte-fmt won; bun-first).
2. **The zone directory is `frontend/microfrontends/*` (R11).** The incoming lance-ns tree is adapted to
   it at copy (Part A item 3): the workspaces glob, `turbo.json`, the zones' `vite.config.ts`,
   `media-api/src/api.ts` and all of `zone-contract/src/` have their `components/frontends` path segment
   replaced with `microfrontends`, in the same commit as the copy, gates re-run.
3. `uvx ty check` clean (the 70 pre-existing rask errors were yours to clear), gates green, committed.

## The copy manifest — R1 is TOTAL; every top-level item has a destination

| lance-ns | → rask | Note |
|---|---|---|
| `frontend/` | `frontend/` — zones land at **`frontend/microfrontends/{home,lakehouse,media,annotator}`** (R11); the 7 `@repo/*` packages at `frontend/packages/*`; `package.json`, `bun.lock`, `turbo.json`, `knip.json`, `microfrontends.json`, `.oxlintrc.json`, `.oxfmtrc.json` at the `frontend/` root — with the `components/frontends` → `microfrontends` path adaptation from Part A item 3 applied in the same commit | The JS plane root is `frontend/`, not the repo root (owner-ruled). rask's `compute` + `studio` merge in as zones; rask's `packages/{api,ui}` fold INTO `@repo/api`/`@repo/ui` (keep rask's storybook + `navMain(project)`). Dev ports: incoming zones take fresh slots — lance `lakehouse` 5174 collides with rask `storage` 5174, lance `annotator` 5177 with `studio` 5177, and R9 keeps studio, so that one is live |
| `services/` (catalog, lineage, medallion, compaction, viewer, search, annotator) | `services/*` | src-layout conversion at copy; entrypoints preserved (`catalog.main:app`) |
| `packages/` (`common`, `ratch` — **ratch already moved**, `45912c8`) | `packages/*` | Workspace members. `common` keeps import root `common` (zero rewrites); `ratch` gains its own pyproject with its ray/lance-ray/typer deps at P1, resolving its old root-tooling exclusion |
| `runners/` (asr, diarize, kg, topics, voiceprint, assist — **already sealed**, `a4cf8f6`) | `runners/` top-level | **ABSOLUTE rule: a runner is NEVER a workspace member.** Each keeps its own pyproject + deps (+ `assist`'s own `uv.lock` and image). rask's `components/cli/runner` (HTR) also lands here as `runners/htr`, sealed, OUT of the workspace — no "resolves today" exception |
| `pyproject.toml` + `uv.lock` + `.python-version` | the workspace conversion — **all three stay at ROOT** | Root `[tool.uv.workspace] members = ["packages/*", "services/*"]` — GLOBS (runners matched by no glob). ONE lock at root, zero member-level locks (rask's existing shape — verified); members declare deps in their own pyproject but never lock. Root `.python-version` (3.13, both repos agree) is the fleet interpreter; uv discovery walks up, so members inherit — **a runner adds its own `.python-version` only when it diverges from the fleet** (the Ray-image case; today none do). Regenerate `uv.lock`; append `tests/unit`, `tests/integration`, `tests/e2e-py` to the explicit `testpaths` with a **collection-count assertion** — silent testpaths loss is rask's own risk 5 |
| `chart/` — **ALL of it** | grafted into `rask/chart/` | Per P4: subchart dedupe (rask's deps, lance-ns's richer values), every template incl. `dapr-statestore.yaml` and `runners.yaml`, all hooks with explicit component labels, NetworkPolicies ported AND extended over rask's fleet, `values-prod.yaml`, `prod_render_check.sh` adapted to `rask-` names |
| `deploy/` | three destinations | `cnpg-age-cluster.yaml` → `chart/templates/age-cluster.yaml` (AGE as a CNPG ImageVolume extension — decided and proven; needs K8s 1.33+); `kind/kind-config.yaml` → keep at `deploy/kind/` — `make kind-up` reads it and kind is this branch's proof vehicle; `ray-lance-demo.yaml` → copy transitional, retired at P5 by the unified RayCluster |
| `.docker/` — all dockerfiles | `.docker/` | P3: `rest-catalog` rewritten for src-layout (`uv sync --package`) and it must cover or split the media trio; `frontend.dockerfile` builds the six-zone set; `assist-runner` builds from `runners/assist`'s own lock; `cnpg-age-ext` as-is |
| `.dagger/` + `dagger.json` | merged into rask's module | One `dagger.json`; `TestPg`/`MigrateUp` untouched; source paths rewritten to the D7 tree |
| `.github/workflows/` | copied, paths adapted | Inert until a push exists; the merged Dagger module is the CI vehicle — local `make ci` / `make e2e-ci` / `make e2e-ray-ci` are the branch's enforcement, logged in the merge doc |
| `tests/` | `tests/unit`, `tests/integration`; Python live suites → `tests/e2e-py` | `tests/e2e` stays the `@rask/e2e` bun package |
| `scripts/` — all | `scripts/` | No name collisions (verified). Object names and ports adapted at P6: `rask-`/`rask-web-` prefixes, gateway `:8888` |
| `docs/` — **copy `OPEN-WORK.md` + `GOAL-UX-REACTIVE-EVIDENCE.md` FIRST, before any code** | `rask/docs/` + zensical nav | `OPEN-WORK.md` is the durable backlog; P8 reconciles it (closed items struck WITH evidence), never drops it. The evidence file is what merged-tree regressions get compared against |
| `lance_docs/` (vendored upstream Lance format docs, 171 files) | `rask/lance_docs/` | As-is |
| `.claude/` + `skills-lock.json` | merged into rask's `.claude` | Combine the skill sets; the `rask-*` skills are redrawn at P8 for the merged fleet |
| `Makefile` | merged | lance-ns's kind lifecycle (`bootstrap/kind-up/deps/images/load/deploy/up`, `e2e-ci`, `e2e-ray-ci`) lands ALONGSIDE rask's k3s targets |
| `Tiltfile`, `.devcontainer/`, `.hadolint.yaml`, `.dockerignore`, `.gitignore`, `.vulture-whitelist.py`, `.python-version`, `README.md` | carried / merged | Reconcile the dev loops (Tilt vs `dev-micro.sh`) at P6 — don't silently drop either |
| `LICENSE` | **surface, don't decide** | Risk 8: lance-ns carries an Apache relabel; rask's identity is AGPL-3.0-only. Restore rask's original labels and flag the question to the owner |

## The traps, in copy order

- **Tailwind `@source` climbs break SILENTLY when a directory moves — audit yours NOW.** Found in lance-ns
  after the same rename you did: each zone's `src/app.css` carried
  `@source '../../../../packages/ui/dist'` — one `../` too many at the new depth, so Tailwind v4 simply
  stopped scanning `@repo/ui` and never emitted its `lg:*` utilities. The entire estate sidebar collapsed
  to `display:none` with **markup present in SSR, zero console errors, zero page errors** — only an
  element-visibility assertion caught it, after a four-experiment bisect. Your exposure is identical twice
  over: your zones moved (`components/frontends/<z>` → `frontend/microfrontends/<z>`) AND your
  `packages/ui` moved into `frontend/packages/ui`, so any `@source '../../../../packages/ui/…'` in a rask
  zone now resolves to the Python-only root `packages/`. Audit:
  `grep -rn "@source" frontend/microfrontends/*/src/` plus `grep -rn '\.\./\.\./\.\./'` over zone files,
  and verify every relative target EXISTS (`python3 -c "import os; print(os.path.abspath(...))"`) from the
  file's own directory. The incoming lance-ns zones are already fixed (`'../../../packages/ui/dist'`).

- **`rask-web-<zone>`** for every frontend k8s object. The live instance of the collision class: the
  `annotator` ZONE vs the `services/annotator` backend Service under one release.
- **The state store** (`dapr-statestore.yaml`): DSN from OpenBao through `lance-secrets`, never a k8s
  Secret; `scopes` must list every app owning operational state or saved work 503s with only a sidecar
  log to show for it — `tests/unit/test_invariants.py` pins the agreement; keep it collected.
- **Live SSE streams**: every zone shell holds one open. Traefik needs the equivalent of nginx's
  `proxy-read-timeout: 3600` or every zone reconnects on a timer, re-priming the event window and writing
  an audit record each time. Verify with `scripts/verify_live_stream_timeout.mjs`, `HOLD_S` past 255.
  Corollary: **`networkidle` can never fire in any zone** — `no-networkidle.test.ts` enforces it; wait on
  the element you act on, or assert the effect with `.toPass()`.
- **Helm**: numeric values use `hasKey` + `ternary`, never `| default` (an explicit `0` is swallowed);
  Job/CronJob pod templates need explicit component labels (prod default-deny blocks them; kindnet hides
  it); never `helm upgrade -f chart/values.yaml` against a live release — `helm get values` first.
- **kind**: after `kind load`, DELETE pods (rollout restart keeps the old digest) and verify the app
  container's `imageID` **by name** — `containerStatuses[0]` is the daprd sidecar on a 2/2 pod. Never
  delete the OpenBao pod: dev-mode, in-memory, every secret dies with it.
- **Gateway rows (P1)**: `/api/catalog→catalog`, `/api/lineage→lineage`, `/api/produce`+`/api/train→
  medallion`, the whole-plane media namespace `/api/media→viewer`, `/api/media/search→search`,
  `/api/media/annotations→annotator` (R5), plus catalog `user_state`/`me`/`access_admin`. lance services
  serve `/v1/...` internally — a wrong strip prefix 404s silently.
- **ratch**: its `cli/` still holds unwired repo-relative `from runners.…` imports (lance-audio
  heritage). They are replaced by the Ray-native name seam (`Stage.runner=` + worker `runtime_env` from
  the runner's own pyproject) — never resolved by making `runners/` importable again.

## Gates for this step

`uv sync` clean · `make check` (ruff format --check + ty, whole repo) · `make test` with the
collection-count assertion (≥67 unit + 13 integration files at the pin; re-derive at copy) ·
`turbo run check test lint fmt:check build` green from `frontend/` across the six-zone set · **the full
`@repo/zone-contract` suite collected and green** — it is the falsifiability layer; if it silently never
runs, every frontend claim is unguarded · helm lint + render invariants (incl. the rendered-name
uniqueness assertion) + `prod_render_check` · all images build and `kind load`.

Then the P6 global live drive on kind: `seed_medallion_fga.sh` + restart lance-ray (green e2e ≠
drive-ready), alice `/produce` 202 / bob 403 / anon 403 → cascade rows per stage → lineage populated →
cross-zone OIDC (sign in on `/lakehouse`, still signed in on `/media` and `/annotator`; alice 2xx / bob
403) → rask's `mfe.spec` green against the SAME deploy → DLQ view + replay → `prod_render_check` green.

Report an honest fraction at each gate. Never mark a gate met on a check you did not run. When a claim
can be settled by reading the tree or running one command, do that instead of remembering.
