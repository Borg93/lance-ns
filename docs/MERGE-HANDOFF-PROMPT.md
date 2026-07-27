# Handoff prompt for the rask session

Copy everything below the line into the rask Opus 5 session. It is written to be pasted verbatim.

---

You are working the lance-ns → rask merge on `/home/blackwell/Desktop/rask`, branch
`feat/lance-ns-merge`. **Read `docs/architecture/lance-ns-merge.md` first, end to end, before touching
anything.** It is the authority: owner rulings R1–R9 are ACCEPTED and supersede any other document,
including `RASK-INTEGRATION.md` in the lance-ns repo.

## Hygiene (from the plan, non-negotiable)

- All commits land on `feat/lance-ns-merge` in `/home/blackwell/Desktop/rask`. **Never push to any rask
  remote. Never commit to or merge with rask `main`.**
- **Never edit `/home/blackwell/Desktop/lance-ns`** — copy out of it only. It is at `main@502150b` and the
  plan is re-pinned there as of 2026-07-27.
- Conventional commits; each phase is one reviewable commit series; each commit cites the lance-ns source
  commit. Git-history grafting is out of scope — provenance is by citation.

## Two preconditions before P1 — both will stop you cold if you skip them

1. **rask's own `ty` gate is RED.** `uvx ty check` on the unmodified branch reports **70 errors**:
   `components/scripts/index_alto.py` (39), `components/services/core` (24), `packages/htr/src` (10),
   `components/services/ray_api` (7), `packages/storage/src` (4). None is lance-ns code. P1's gate requires
   `make check` green, and the **pre-commit hook enforces it — so you cannot commit anything** until this is
   cleared. Do it as a standalone pre-P1 commit, provable against rask alone. Do not relax the gate to
   accommodate them; that is the failure this plan exists to prevent. (The plan's own re-pin commit needed
   `--no-verify` for exactly this reason.)
2. **The toolchain direction is RULED (R10) — lance-ns's wins.** oxlint + oxfmt + rsvelte-fmt replace
   rask's eslint + prettier, and the chart and all lance-ns configs come with the merge. What remains is
   the *execution*: one pure-format commit reformatting rask's surviving zones (`compute`, `studio`, home
   content) and `packages/{api,ui}` under the lance-ns toolchain, **before any 3-way merge** — or the
   formatter noise gets baked into the conflicts. `@repo/zone-contract`'s script-parity gate then applies
   to every package unchanged.

## What changed in lance-ns since the plan was first written (190 commits)

Full detail: `/home/blackwell/Desktop/lance-ns/docs/MERGE-REPIN-DELTA.md`. The three that break the old plan:

- **Four zones, not seven.** `home`, `lakehouse`, `media`, `annotator`. The old `data`/`lineage`/`models`/
  `admin` zones were merged into **one `lakehouse` zone** — they are its *routes* now. One app, one port
  slot, one ingress rule, one image, one spec dir.
- **`@repo/*`, not `@rask/*`.** Seven packages: `api`, `ui`, `config`, `engine`, `labeling`, `media-api`,
  `zone-contract`. The last two are net-new. **`zone-contract` is the package that makes the frontend
  claims falsifiable** — wire its suite into rask's test run or it silently never executes.
- **`frontend/eslint-rules/` does not exist.** The cross-zone-reload guard is a *test* in `zone-contract`.

Also new and absent from the old plan: the **Dapr state store** (`chart/templates/dapr-statestore.yaml`),
the **runners** deployable, catalog `user_state`/`me`/`access_admin` endpoints, and a **run-notification SSE
transport** mounted in all four zone shells.

## R8 + R9 — the surviving zone set

**`home + lakehouse + media + annotator + compute + studio`** — six zones.

- rask's **browse / viewing / search** surfaces are eaten by the media plane (R6, reconfirmed): the
  `discover` zone, the EAD `/api/v1/catalog` endpoints, `search_api`, and `volumes_api`'s page/ALTO viewing
  all retire.
- **`compute` survives** — Ray dashboard, jobs, actors, cluster. It is the plane rask owns.
- **`storage` folds INTO `lakehouse`** — an S3 object browser is a lakehouse view of the warehouse's own
  buckets, not a separate destination.
- `train` folds in with it (lance `models` absorbed it, and `models` is a lakehouse route).
- `overview` folds into `home`.
- **`studio` survives as its own top-navbar zone (R9).** It is not folded into anything. That matches what
  it already is here: a top-level entry in `packages/ui/src/lib/shell/nav-config.ts:81` (`Studio`, `Shapes`
  icon) with its own `/animation` route.

## The layout target — D7, settled by experiment (owner-ruled 2026-07-27)

Two **language-pure planes**, not one mixed root `packages/`. The deciding facts, reproducible in a
scratch dir: `uv lock` **errors** on a non-Python dir matched by a members glob (an `exclude` list is
enumeration renamed), and `bun install` **silently skips** non-JS dirs — safe-looking until a Python
package gains a `package.json` and gets swept in without a word. Language-pure directories are the only
shape where globs are both possible and safe, and there are **zero cross-language package deps** in either
repo.

```
frontend/     ← lance-ns's JS plane, WHOLESALE: bun.lock, turbo.json, oxlint/oxfmt configs, and all 13
                @repo/zone-contract gate files travel unchanged. rask's compute + studio move INTO it.
services/     ← Python deployables, src-layout: catalog, lineage, medallion, compaction, viewer, search,
                annotator + rask's gateway/core/ray_api + runners/assist. components/ dissolves.
packages/     ← Python-only shared: common, ratch, storage, service-kit, ray-kit, htr, tracker, validate.
pyproject.toml  [tool.uv.workspace] members = ["packages/*", "services/*"]   ← GLOBS, no enumeration
```

Consequences you must apply:
- **The P0 frontend direction FLIPS**: do not graft lance zones into `components/frontends` — move rask's
  two surviving zones into `frontend/`. Fewer moves, and the proven gates arrive as-is.
- **P2's `packages/ui` merge inverts**: rask's storybook + `navMain(project)` fold INTO `@repo/ui`.
- The manifest-completeness gate is unnecessary under D7 — globs enforce membership structurally.
- `packages/ratch` → `packages/ratch` (a *package*, owner-ruled — its heavy deps move into its own pyproject,
  which resolves its current exclusion). Per-individual-service packages are rejected: shared-by-one is
  not shared.

## Landmines that already cost real time — do not rediscover them

- **`waitUntil: 'networkidle'` can never fire again in any zone.** Every shell holds a `query.live` SSE
  stream open by design, so an idle-network wait sits until its timeout and reports the product as hanging.
  Ten such waits were replaced in lance-ns; `@repo/zone-contract/no-networkidle.test.ts` fails on a new one.
  Wait on the element you are about to act on, or assert the effect and retry with `.toPass()`.
- **The live stream needs the ingress to permit it.** Proven at 270.1s with 0 severed on nginx via
  `proxy-read-timeout: 3600`. **rask uses Traefik** — find its equivalent, or every zone reconnects on a
  timer and each reconnect re-primes the event window and writes an audit record.
  `scripts/verify_live_stream_timeout.mjs` takes `HOLD_S`; run it past 255 against rask's ingress.
- **k8s object names**: every frontend zone object must be `rask-web-<zone>`. A bare zone name collides with
  a backend Service selector — lance-ns hit exactly this, and the live instance in the merged tree is the
  **`annotator` ZONE vs the `services/annotator` BACKEND** under one release.
- **The dev ports collide.** lance `lakehouse` 5174 vs rask `storage` 5174; lance `annotator` 5177 vs rask
  `studio` 5177 — and R9 keeps `studio`, so that one is live rather than incidental. The three incoming
  zones need fresh slots (the plan proposes lakehouse 5180, media 5181, annotator 5182). rask currently
  holds home 5273 / overview 5179 / storage 5174 / compute 5175 / discover 5178 / train 5176 / studio 5177.
- **Job/CronJob pod templates need an explicit component label** or prod default-deny blocks them. kindnet
  hides the violation, so it only appears in prod.
- **`helm --reuse-values`**: a new values key renders EMPTY under it. All new numeric keys use
  `hasKey` + `ternary`, never `| default` — `default` treats an explicit `0` as absent.
- **kind same-tag images**: rebuilding under a reused `:dev` tag and rolling out does NOT update running
  pods. `kind load`, then **delete** the pods, then verify the pod's `imageID` digest actually changed.
  Read the app container **by name** — `containerStatuses[0]` is the daprd sidecar on a 2/2 pod.
- **Deleting the OpenBao pod wipes every secret** (it runs `server -dev`, in-memory) and nine pods then
  correctly fail closed. Never include it in a redeploy sweep; if it dies, re-seed before restarting anything.
- **The state store's `scopes`** must list every app that owns operational state. An app outside `scopes`
  gets "component not found" from its sidecar and every user's saved work 503s — logged by the sidecar and
  noticed by nothing else. `tests/unit/test_invariants.py` pins the agreement; keep that test.

## What to verify rather than assume

- **Green gates are a floor, not a finish.** In lance-ns, two adversarial passes returned 4/4 REFUTED on
  claims that were already pushed and green, including an anonymous 6.6 MB read reachable in two zones.
- **Drive the product, not the elements.** The notification bell was shipped, shared, and tested — and
  mounted in **one zone out of four**. Nothing was red. Only signing in and looking found it.
- **Take screenshots and open them.** Element crops at `deviceScaleFactor: 3`; when you suspect a defect,
  measure it in the DOM (`clientHeight` vs `scrollHeight`) rather than judging by eye. A `line-clamp` with a
  `title` is intentional truncation; a two-pixel overflow with no marker is a clipped descender.
- **CI-only failures are real failures.** lance-ns main was red for five runs on two causes invisible
  locally: `svelte-kit sync` racing `vite build` over `.svelte-kit/types` (turbo `check` must depend on its
  own package's `build`), and Playwright `workers: 8` starving a small runner (`CI ? 2 : 8`). rask inherits
  neither fix automatically.

## Carried-over open work — read `docs/OPEN-WORK.md`, it travels with the merge

`lance-ns/docs/OPEN-WORK.md` is the durable backlog and the plan's P0 copies it to `rask/docs/OPEN-WORK.md`.
It is self-describing — what each item is, why it is open, where the code lives, what closes it — because
the old record was session task IDs that outlive nothing. **P8 reconciles it: items the merge closed get
struck with the evidence, the rest carry forward, none silently dropped.**

Two entries change what you do rather than waiting for you:

- **A1 — the media corpus must leave its node hostPath.** Deferred in lance-ns, **blocking here**: P4 rules
  no hostPath ships. Split it — registering the corpus as catalog-governed project tables is portable and
  worth doing first; the physical destination (PVC vs a rustfs-backed bucket on rask's Tenant) belongs in
  P4, decided once against the cluster it will live on.
- **D · annotator export serializers** (COCO / YOLO / CSV / HF) are the **same service** as P7c's `exporter`
  (ALTO 4.4 first, R4). Additional projections from gold, not a second export path. Do not build it twice.

Also open, all with stated reasons in that file: the state store has **no actor type and no workflow
registered** (the `actorStateStore` flag is on and unused), the notification inbox has no actor, annotation
projects are designed but need those actors, `TableDetail`'s reset effect needs its own pass (an edit there
dropped 6 of 10 history versions with `svelte-check` at 0 errors), the product-works pass, the gold
whole-history JSONB embed — which is the same artifact as your **P7b gold schema contract**, so do it once,
there.

## Start here

1. Read `docs/architecture/lance-ns-merge.md` in full.
2. Clear rask's 70 `ty` errors as a standalone commit; confirm `make check` and the pre-commit hook pass.
3. Land the R10 pure-format commit (lance-ns toolchain over rask's surviving zones and packages).
4. Then P1, per the plan — with D7's tree as the copy destination. No zone or structure decision is outstanding.

Report an honest fraction at each phase gate. Never mark a gate met on a check you did not run.
