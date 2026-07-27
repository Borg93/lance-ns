# Goal: verify the claude.ai pull for real — live tracker

The pull (25 commits, `3f17543..e489f2b`) was written in a sandbox with **no docker, kind or helm**.
Everything in it was unproven against an image, a chart or a cluster. This file is the single place the
goal, the conditions the owner added mid-flight, the evidence, and what is left all live — so none of it
is carried in conversation memory alone.

## Where we are, in one table

The owner asked, fairly: *"why is there no goal md? Seems like we are not tracking stuff and is far away
to reach the goal."* This file existed and was current, but answering that question took reading 38 KB of
it — so this is the ledger. One row per thing the owner asked for, newest asks last. Detail for every row
is further down or in the linked audit.

**The six original conditions are closed, and so are eleven of the fourteen asks added after them.**
Three rows are still open on purpose and say why: #111's remaining lineage parity, #122's build (designed,
slices listed), and #103's media plane on the governed warehouse, which predates this goal entirely.
"The goal" therefore means two things, and the second one — the UX track — is the one still moving.

Last made true: **2026-07-26**, after the twenty-condition UX pass. Every "Closed" row below cites the
command output, commit or screenshot that closed it; none of them is closed on my say-so.

| Ask | Task | State | What remains |
| --- | ---- | ----- | ------------ |
| Original conditions 1–6 | — | **Closed** | Nothing. Fractions and evidence at the foot of this file |
| Navbar IA (four triggers) | — | **Closed** | Nothing; Compute stays unrendered until the zone exists |
| Component reuse / one ui lib | #120 | **Closed** | Nothing — `AppShell` gained `canvas`, annotator dropped its forked header |
| Search modes must be honest | #123 | **Closed — decided** | A URL, not a Deployment: the servers are stock `vllm/vllm-openai` serving 4.27 GB checkpoints and this cluster has **no `nvidia.com/gpu` in node capacity**. Wiring proven live (503 → 200 via `encoders.*Url`). UI already renders unavailable modes disabled with the reason |
| Git-like data history | #113 | **Closed** | Live: `/v1/table/{id}/history` in the running catalog's OpenAPI (101 paths), all 10 versions rendered, the delete predicate `id = 2` verbatim, alice 200 / bob 403. Four backend defects fixed on the way (`2c01ea0`) including `Restore.version` colliding with the row's own key |
| Lineage track | #111 | **Part landed** | Spec-fidelity and Marquez-parity reports. Gold finding + Dapr-delivery tests already in `b43b8ff` |
| Reactive data flow | #102 | **Closed** | 13 timers → 1 per zone: `home 0 · lakehouse 3 · media 1 · annotator 0`, where lakehouse's 3 are two prose mentions plus one justified survivor. Enforced by `poll-reason.test.ts` (`8bbdb61`), which fails on any unexplained timer — the count alone was not a gate |
| Interactive state has no home | #124 | **Half closed** | The store is LIVE and proven: `lance-statestore` (`state.postgresql` on the existing AGE Postgres, DSN from OpenBao via the Dapr secret store), actor state store enabled, write/read/delete round trip, an unscoped app correctly refused. Actors for #122 and workflow for the publish saga are NOT built |
| Annotate is its own domain | #122 | **Designed, not built** | `docs/DESIGN-annotation-projects.md` — entities, both state machines, the authz doors, what a publish emits, and a slice plan. Slices `S1`–`S4` (domain core, FGA type, publish schema, catalog `create` pin) need no store; `S5`–`S10` are #124. *Delegated to me 2026-07-26* |
| Lance OTel | #114 | **Closed** | I was wrong that it was unstarted: the bridge and its five lifespan hooks were written ahead of the release and lay dormant. pylance 8 → 9 (`e7c0504`) activates them — `instrument_lance_if_available()` returns True against the real dependency |
| Storybook | — | **Struck for now** | `find -name .storybook` → **0**. The case is real — presentation bugs keep evading assertions — but adopting it is a tooling pass; this session the screenshot rule caught them instead, four times |
| Annotator bundle weight | #117 | **Closed** | OpenCV gone: `grep -c opencv frontend/packages/engine/package.json` → **0**. The dependency was carrying four operations; `corners.ts` implements them with a golden-file test, net −213 lines (`fd787cd`) |
| Zone images in CI | #118 | **Closed** | `.github/workflows/ci.yml:146` — a `zone-images` job builds all four and smoke-runs each container against its own base path (`927ac84`) |
| Viewer OOM | #121 | **Closed** | 1536Mi/768Mi, sized from measured cgroup peaks rather than guessed (955Mi high-water during the KG build). 0 restarts under the load that killed it (`629b1b1`) |
| `TableDetail` reset effect | #119 | **Deferred with reason** | `{#key table}` under 191 e2e tests; its own pass |
| Settings surface | #112 | **Deferred by owner** | "Keep it as is" |
| Media plane on the governed warehouse | #103 | **Not started** | Corpus as registered project tables rather than hostPath. Predates this goal; listed so it is not lost |
| Notifications + progress tracking | #125 | **Closed, estate-wide** | It first shipped in **one zone out of four** — the component was shared, the transport was not, so `bell in home: 0 · lakehouse: 1 · media: 0 · annotator: 0`, and the zones where someone waits on a batch were the three without it. Fixed by lifting the feed to `@repo/api/runs-feed` (`19de3f1`); gated by `notification-surface.test.ts`, which fails per zone on a missing mount or a forked feed. Driven live for alice **and** bob in all four. Needed no new backend — `GET /runs` already folds lifecycle into START/RUNNING/COMPLETE/FAIL. Driven in the lakehouse zone against **891 real runs**: bell in the navbar, two Failed rows on top with their errors, five completions below (`3000ba4`). Two defects found live: the first FAIL sat at position 445 so no failure could ever show, and its error rendered a 25-line stack trace that filled the panel |
| Verify by looking | — | **Standing rule** | Active, and it has earned itself four times |
| **UX track — reactive, stateful frontends** | #102 #124 #125 | **all 20 conditions proven** | `docs/GOAL-UX-REACTIVE.md` grew from 7 conditions to 20 as the adversarial pass returned. Met: **1–20**. The last five closed by one drive (`verify_all_zones_both_users.mjs`) that found the bell shipping in one zone out of four, three of my own measurements wrong before the product was, and `networkidle` waits that can never fire again |

Five of these were waiting on an owner decision rather than on work — #123's deployment half, #122's task
schema, #118's runner minutes, #121's memory limit, #117's bundle budget. **The owner delegated all five on
2026-07-26** ("ofc track aswell and fix"). Four are now decided and closed above with the reasoning that
decided them; #122 is decided in design (`docs/DESIGN-annotation-projects.md`) and unbuilt, because slices
`S5`–`S10` stand on #124's actors, which is the half of #124 that is not done.

The ordering that got the most user-visible improvement per unit of work turned out to be exactly
#124 → #102 → #113's view — #124's state store is what #102's push signal, #122's projects and #125's
notifications all stand on, and it landed first.

## The rask merge — where it stands (2026-07-27)

The authority is **`rask/docs/architecture/lance-ns-merge.md`** on `feat/lance-ns-merge`, not
`RASK-INTEGRATION.md` here. Direction is settled by **R1: total merge, lance-ns → rask**. The file-count
asymmetry (lance-ns 1643 tracked files vs rask 639) argues the other way and is the wrong measure: rask's
side is *empirically tuned infrastructure* — KubeRay + Kueue with GPU Serve packing OOM-tuned against a
raylet-killing cascade — which you re-tune rather than copy. Ours is application code plus a chart, and its
proof travels with it. You move the code to the compute.

**Owner rulings R8 + R9 (2026-07-27)** — the surviving zone set is
**`home + lakehouse + media + annotator + compute + studio`**, six zones: rask's browse/viewing/search are
eaten by the media plane, `compute` survives as the plane rask owns, `storage` folds INTO the lakehouse,
`train` folds in via `models`, `overview` into `home`, and **`studio` keeps its own top-navbar entry (R9)**
— it is not folded into anything, which matches what it already is on the rask side
(`packages/ui/src/lib/shell/nav-config.ts:81`).

**The plan was 190 commits stale** and is now re-pinned (`df70b63` → `502150b`, rask commit `2d80e49`).
Three drifts were structural, not cosmetic — four zones not seven, `@repo/*` not `@rask/*`, and
`frontend/eslint-rules/` gone. Two preconditions it lacked are now recorded: **rask's own `ty` gate is red
(70 errors on its unmodified tree**, which blocks every commit via its pre-commit hook) and the two repos
have **incompatible frontend toolchains**.

Working detail: [`MERGE-REPIN-DELTA.md`](MERGE-REPIN-DELTA.md). Copy-pasteable brief for the rask session:
[`MERGE-HANDOFF-PROMPT.md`](MERGE-HANDOFF-PROMPT.md).

## Standing rules (owner-set)

- **Evidence, not assertion.** Every claim cites command output, a rendered manifest, or a screenshot.
  "Looks right" is not evidence.
- **Nothing lands without a test.** A fix that cannot fail a gate has not been verified — if a gate is
  the thing being fixed, break it deliberately and watch it fail before trusting the green.
- **Backward compatibility does not matter.** It is far too early. Do not preserve old paths, old
  names, old shapes, or old flags for compatibility's sake — change them to the right thing and update
  every caller and every test. (Owner, 2026-07-26.)
- **Fix, don't just report.** Commit in reviewable units, PLAIN conventional messages, no trailers.
- Skills are to be **invoked and read**, not skimmed: turborepo, micro-frontends, svelte-5 (+ svelte
  MCP), writing-python, fastapi, openfga, dapr, testing-python.

## The six original conditions

| # | Condition | Status |
| - | --------- | ------ |
| 1 | Architecture verified against the skills (turbo.json, 4-zone MFE, Svelte 5) | **DONE** — turbo.json (empirical cache proof), MFE and Svelte 5 all audited + adversarially verified; 3 bugs fixed, 2 deviations recorded with reasons |
| 2 | Toolchain migration complete (no eslint/prettier; identical scripts; gates real) | **DONE** — 3 defects fixed, and the gate proven to FAIL on drift in both directions: changing media's `lint` to `eslint .` → *"media is missing the shared lint script: expected 'eslint .' to be 'oxlint .'"*; DELETING its `fmt:check` → *"expected undefined to be 'rsvelte-fmt --check .'"*; restored → 79/79 green, tree clean |
| 3 | Zones/routes/abstractions right; judged against the Lakekeeper console | **DONE** — 26→26 parity, orphan sweep (one orphan: `/lakehouse/admin`), 8 gaps + 6 advantages vs their console, one recommendation |
| 4 | media/annotator split sound and documented; Pixi recommendation | **DONE** — backends separate (live pod env), reuse quantified (4 of 5 `@repo/*` shared), Pixi verdict written, and the bundle-budget gate it exposed is fixed + tested |
| 5 | The cluster TODO (`docs/TODO-CLUSTER-VERIFY.md` §1–6) discharged | **DONE** — 35 ticked with evidence, 2 struck with the reason; zero ambiguous boxes remain. The condition's own wording is "ticked with evidence **or** struck with a stated reason" |
| 6 | All gates green, stale dirs deleted, pushed, CI confirmed | **DONE** — every gate green, pushed `e489f2b..f8f1480`, CI `test` job green, rest under watch |

## Conditions the owner added mid-flight

| Added | What | Task | Status |
| ----- | ---- | ---- | ------ |
| Lineage track | OpenLineage spec fidelity; Dapr/FastAPI/Ray test coverage; Marquez parity; gold JSONB-in-Lance | #111 | Agent work salvaged; gold finding landed. Spec/coverage/parity reports partial |
| Dapr sweep | Is Dapr missing anywhere in the lance-audio merge (viewer/search/annotator)? | #124 | **CORRECTED 2026-07-26 — the first verdict was too generous.** No *required* annotation is missing: all three carry a sidecar (live pods 2/2) with `dapr.io/config: lance-tracing`. But they USE none of it — measured: viewer/search/annotator each `publish:0 subscribe:0`, zero Dapr imports, against medallion 4/7, catalog 2/2, lineage 0/3, compaction 1/2. Wired for Dapr, using tracing only. The annotator saves a label and publishes nothing, so nothing downstream can react — and that is the same gap as #102 one layer down: the frontends poll because this plane never emits |
| Git-like data history | Answer "what changed, by whom, when" from Lance transactions/manifests/tags+branches, Lakekeeper-style | #113 | **Feasibility PROVEN against pylance 8** — see the section below. The format supplies what/when; the blocker is that mutating control events do not stamp the resulting version, so "who" has no join key |
| Lance OTel | Wire Lance's own observability into our OTLP→Collector→GreptimeDB path | #114 | NOT STARTED |
| Navbar IA | Four triggers: Lakehouse (incl. lineage + admin), Search, Annotate, Compute (after rask) | — | **DONE** — Compute deliberately unrendered until the zone exists |
| Settings surface | Break out auth / authz / audit into their own surface | #112 | Deferred by owner ("keep it as is") |
| **Annotate is its own domain** | Annotation state is the annotator's OWN state, **not** the lakehouse's — synced only when we choose to. Labeling project management is a different thing from the app shell's project-as-tenant, with **tasks** as the unit of work like any labeling platform. Items arrive by being SENT from search/atlas/saved view; the landing page is your projects and their progress, not the corpus | #122 | NOT STARTED. **Corrects an earlier note of mine that said a project should "reference governed table rows"** — that is the coupling the owner ruled out. Two stores, one deliberate crossing point: a finished project is PUBLISHED to the lakehouse (governed table + lineage) and nothing lands before that, which is what makes half-labelled, re-labelled and abandoned work safe. **Schema decided 2026-07-26 in `docs/DESIGN-annotation-projects.md`** — four entities (project/task/draft, no `Assignment`: the lease *is* the assignment), one six-state task axis (Label Studio's lease + reviewer vocabulary, CVAT's return-on-reject, not CVAT's stage×state), publish gated on every task terminal and on **two** FGA doors, and a 34-column published table that deliberately carries no task state. The store it needs does not exist: #124 |
| **Search modes must be honest** | Vector/Hybrid/Rerank were offered on a deployment with no encoder | #123 | **UI half DONE** (`56e3388`) — modes needing an encoder render "encoder offline", disabled, health-driven so they self-enable. Deployment half is an owner decision: deploy an encoder or declare semantic search out of scope |
| **Component reuse / one ui lib** | Consistency between the apps; put more in `@repo/ui` | #120 | **DONE** (`6e809b4`, `90a2709`) — AppShell gained a `canvas` variant and the annotator dropped its forked header. A missing variant is why a zone forks a shared component |
| **Storybook** | Are we using it? | — | **No — nothing in any package.json, no `.storybook` anywhere.** Worth adding: the two presentation bugs this session (navbar clipped to 69px, avatar on the left) were invisible to 191 e2e tests and obvious in a screenshot |
| **Verify by LOOKING** | Take screenshots when touching the frontend, and open them; drive with playwright | — | **Standing rule, owner-set twice.** It has earned itself: looking caught the clipped navbar panel, the annotator's 502, the missing canvas divider, and one of my own assertions that passed while asserting nothing |
| **Interactive state has no home** | Why is no Dapr KV / cache / state management / actor used, when Lance is OLAP? | #124 | **The owner is right, and it is one fault not four** — see `docs/DESIGN-interactive-state.md`. The UI polls because there is no event to subscribe to; there is no event because viewer/search/annotator publish nothing; they publish nothing because there is no operational state model to publish about. Lance cannot hold it: a per-task state flip would be a dataset version, so hundreds of manifests a minute and a history that is noise rather than provenance. Needs a state store (`actorStateStore: "true"`, which gates actors AND workflow), then #122's task state on it, then publish-on-save, then `query.live` per feed |
| **Reactive data flow** | Every zone refreshes itself on new data/events — no hand-cranked polling, no "weird refresh back"; decide where state/cache/KV belongs | #102 | **MEASURED, largest remaining frontend item.** The right pattern exists in ONE file: `admin.remote.ts` uses `query.live()` — a server-side generator holding cursor + window + dedup, yielding only on change, with SvelteKit owning the stream and reconnect. Everywhere else polls from the client: **15 `setInterval` files** (lakehouse 13, media 1, engine 1), **0 `EventSource`**, **no client query cache**. So two panels on the same entity can disagree, and a mutation in one does not refresh another until a timer fires. See #102 for the pattern to standardise on and the one genuinely open question (event scoping for non-admins, since `/v1/events` is gated on `can_observe_events`) |

## Defects found and fixed (the actual output of this pass)

| Defect | Why it mattered | Commit |
| ------ | --------------- | ------ |
| `zoneDirs()` counted gitignored build husks as zones | **39 test failures** across all four gate files in any tree that had built pre-merge | `7df035d` |
| NATS monitor NetworkPolicy admitted `web-admin` | The merge deleted that component, so the rule matched NO pod: prod ops view cannot reach varz/jsz. Default-deny fails **closed and silently** — only symptom is an empty panel | `f4c545d` |
| `prod_render_check.sh` checked four deleted zones' PDBs | Reported a missing `web-data` PDB instead of the real bug above | `f4c545d` |
| Script gate skipped absent tasks (**vacuous**) | `@repo/config` shipped no lint/fmt scripts → outside the toolchain with every gate green | `d28a334` |
| `oxlint .` exits 1 with no files | Naive fix would mask a zone whose paths stopped matching; the required command is now derived from the filesystem | `ffcfcaa` |
| TOOLING.md overclaimed prettier removal | prettier is still installed — pulled by `@rsvelte/fmt` itself via `prettier-plugin-tailwindcss` | `d28a334` |
| Stale `@repo/engine` lockfile entry | package.json had dropped it; lock had not been regenerated | `d28a334` |
| Lineage was a navbar trigger AND an area of the lakehouse zone | Mixed levels; forced Lakehouse to carve lineage out of its own match | `3349e5c` |
| Annotate buried as a row in Search's panel | The annotator is its own zone; one trigger per zone | `d8d3411` |
| **Gold never embedded JSONB lineage** | Docs, seed and demo header all described behaviour the product does not have. Stale, not dangerous: the only reader is disabled | `b43b8ff` |
| **A duplicate tuple in a batch FGA write dropped its siblings** | OpenFGA's Write is one transaction, so an already-existing tuple rejects the whole call — and `write_tuples` swallowed that as "already idempotent". The warehouse creator silently lost `owner` on their own warehouse. This is what made `e2e-stack` red (`can_create_namespace required on warehouse:e2e-wh-a`), and it hid for two days because the job is gated `needs: test` and was **skipped on every one of the pull's own runs** | `363de65` |
| **The bundle-budget gate measured deferred bytes as entry cost** | It gzipped every emitted file and called it "what the browser pays to enter a zone". 3809 of the annotator's 4179 KB is OpenCV behind a lazy import, so a doubling of the entry graph would have passed the gate. It also made the estate unreadable: measured on entry cost, media is the heaviest zone and the annotator the second-lightest — the opposite of what `budget.json` and the split-pays-for-itself test both asserted | `56a6aad` |
| **A security test was red on 3% of runs at random** | `expect(sealed).not.toContain('AT')` in the sealed-cookie test: a 2-char needle against ~130 base64url chars of ciphertext. Measured 616/20000 = one CI run in 32, and a random red on a security assertion trains people to re-run instead of read. It reddened `f0db47c`'s run | `5d4d1d8` |
| Zone e2e suites are FLAKY locally | `fullyParallel` + ~32 workers + `retries: 0` (CI uses 1): a cold Vite cache times out the first wave. Two identical runs gave **12 then 6** failures — I twice misread that variance as my own edits regressing. Use `--retries=1 --workers=8` for a true signal | `18c233d` (recorded) |
| The `Search` rename collided with a form button | Two buttons named Search on `/lakehouse/admin/access` (navbar trigger + Tuples submit) tripped Playwright strict mode; locator scoped to the form | `18c233d` |
| 138 MB of husk directories | admin/data/lineage/models/rask-ui, zero tracked files | deleted |
| Playwright chromium missing | The pull bumped `@playwright/test`; all four suites failed to launch | installed |

## Cluster evidence (condition 5 / TODO §1–6)

- 4 images build; each runs **uid 10001 non-root**; `home` 200 at `/`, `lakehouse` 307 → `/lakehouse/data` → 200.
  Sizes: home 1.32 / lakehouse 1.34 / media 1.35 / annotator 1.42 GB — annotator only ~8% above, so Pixi
  + OpenCV wasm is not the blowup the TODO feared.
- Chart renders exactly four `web-<zone>` Deployments, no stale ones. **Per-zone tags move
  independently**: pinning only `media` to `probe-xyz` left the other three on `dev`.
- Env scoping: media = VIEWER+ANNOTATOR+SEARCH; annotator = VIEWER+ANNOTATOR, **no SEARCH_API**;
  home/lakehouse neither. Verified on the rendered Deployments.
- Ingress: `/lakehouse`, `/media`, `/annotator` Prefix + `/` catch-all last; base paths agree.
- Auth: anonymous page → 302 `/auth/login?redirect=…`; anonymous API → 401 `problem+json`.
- **bob (non-admin): 403 at the DOCUMENT level, zero admin HTML shipped, no Governance/Operations
  columns in his panel.**
- Anonymous writes → 401 at the BFF on `/access/check` AND `/access/tuples`; service-credential GET → 200.
- **Sealed session survives real ingress hops**: bob stayed signed in across `/media` → `/annotator` →
  `/lakehouse/data`, each a full document load into a different app.
- Gate weakness noted: the dockerfile HEALTHCHECK probes `/` and accepts `<500`, so a based zone reports
  healthy while 404ing the probe. Defensible (proves the SSR server is alive) but it never exercises the app.
- **The batch-write authz bug was reproduced and then fixed on the live cluster**, not argued from code:
  writing `[existing, new]` straight at OpenFGA left only `existing` behind (so the transactional
  all-or-nothing claim is measured, not assumed); the deployed catalog then gave warehouse-create 200 with
  **zero tuples** on the warehouse and namespace-create 403; after `docker build` → `kind load` → pod
  delete (imageID digest confirmed changed to the new build) the identical flow returned 200 with
  `owner` + `project` present, and the warehouse broken by the old code recovered its `owner` grant on an
  idempotent re-POST.

## turbo.json audit (condition 1)

Cache correctness proven **empirically, both directions**: unchanged → `1 cached >>> FULL TURBO` (20ms);
one input byte changed → `0 cached` (162ms); reverted → cached again, tree clean.

The two failure modes the turborepo skill flags are both absent, and that is load-bearing:
no `incremental`/`composite` anywhere (so `check` with `outputs: []` is correct), and **zero
`$env/static` usage** (so nothing is baked at build time and a cached bundle cannot carry stale env).
`globalPassThroughEnv` carries CI + PLAYWRIGHT_* — the skill's own fix for strict-mode filtering.
Two defensible deviations: `.svelte-kit/**` in outputs (the budget gate weighs `output/client`, so it
must be restored) and `test → build` per package (the transit-node pattern would parallelise better).

## media / annotator: reuse, Pixi, and the bundle-budget consequence (condition 4)

**Backends are genuinely separate** — verified earlier on the rendered Deployments and the live pod env
(media gets VIEWER+ANNOTATOR+SEARCH, annotator gets VIEWER+ANNOTATOR and **no** SEARCH_API).

**Frontend reuse, quantified.** Of the five `@repo/*` packages the two zones could share, they share
**four**: `@repo/api`, `@repo/labeling`, `@repo/media-api`, `@repo/ui`. The fifth, `@repo/engine` — the
Pixi canvas — is **annotator-only**: it is declared in `components/frontends/annotator/package.json` and
nowhere else, and media's source contains **zero** references to pixi or to `@repo/engine`.

**So no, media and the annotator do not share a viewer — and the reason is not duplication.** Media has
no single-item viewer to share one with. Its six pages are all *many-item* surfaces: search (`/`),
`atlas`, `graph`, `tree`, `workflow`, `guide`. Clicking a search hit has nowhere deep to go, so there is
no surface on which a canvas would mount. Media renders thumbnails as plain `<img>` tiles and drives its
own WebGL for the atlas/graph (`gpu-scatter.svelte`, `gpu-graph.svelte` — embedding-atlas + d3, not Pixi).

**Recommendation (not implemented — it needs a product decision first).** The missing piece is a media
item-detail view. When it lands it should mount `@repo/engine`'s canvas rather than grow a second
pan/zoom implementation, and that requires splitting the package along a seam it does not have today:

- `@repo/engine/canvas` — the Pixi surface, pan/zoom, layers. What a *viewer* needs.
- `@repo/engine/tools` — rect/polygon/lasso/brush, undo/redo, and the magnetic tool. What a *labeller*
  needs. This half is what pulls OpenCV.

Media would import only `canvas`. Bundle consequence, measured: the three Pixi-bearing chunks in the
annotator's entry graph are **75 KB gzipped** (an upper bound — they carry engine code too), against
media's current 927 KB entry cost, so ~8%. The OpenCV wasm — **3809 KB gzipped** — must not follow, which
is exactly what the split buys and what the new `the OpenCV wasm stays lazy` gate enforces.

### The bundle-budget gate was measuring the wrong thing

Chasing that number found a defect worth more than the recommendation. `budget.test.ts` gzipped **every**
emitted `.js`/`.css` and its docstring called the result "what the browser pays to enter a zone". For the
annotator that was false by an order of magnitude — 3809 of its 4179 KB is one chunk reached only through
a dynamic `import()` inside the magnetic tool:

| zone | entry cost (static graph) | deferred | old single number |
| ---- | ------------------------- | -------- | ----------------- |
| home | 157 | 1 | 158 |
| lakehouse | 490 | 46 | 536 |
| media | **927** | 46 | 973 |
| annotator | **324** | 3854 | 4179 |

Two consequences, both worse than the wrong number itself:

1. **The gate could not see the regression it exists to catch.** The annotator read 4179/4800 — 87% of
   budget "used" — while its real entry cost was 324 KB. A change that *doubled* the entry graph would
   have passed silently, because 400 KB is noise beside a 3.8 MB constant.
2. **It made the estate's shape unreadable, and the repo believed it.** On entry cost the annotator is the
   second-lightest zone and **media is the heaviest by ~3×** — the opposite of what `budget.json`'s note
   asserted ("this number is the entire reason the annotator is a zone of its own"), and the opposite of
   what the test named `the annotator split still pays for itself` asserted, which compared the *declared*
   numbers and never measured anything.

Fixed by measuring the two halves separately, from Vite's own manifest (`imports` vs `dynamicImports` —
a regex over minified output cannot tell `import"./x.js"` from `import("./x.js")`). Both halves are now
ceilinged, the OpenCV-stays-lazy invariant is a named test, and the split-pays-for-itself test now
asserts the true relation (annotator entry < media entry, annotator deferred > media deferred). Each new
gate was broken deliberately and watched to fail: static ceiling 420→300 → *"annotator loads 324 KB
gzipped on entry, over its 300 KB budget"*; deferred 4200→1000 → *"ships 3854 KB behind dynamic
imports"*; and pointing the OpenCV detector at a marker that *is* static (`pixi.js`) reddened it on
exactly the 3 chunks measured independently.

## #113 git-like data history — what the format actually gives us (verified, not assumed)

Before designing anything: probed pylance 8.0.0 against a real dataset (create → append → delete → update)
in `scratchpad/histprobe.lance`. `LanceDataset.get_transactions(n)` and `read_transaction(version)` exist and
return a `Transaction` per version whose `operation` carries the substance:

| version | operation | what it tells us |
| ------- | --------- | ---------------- |
| 1 (create) | `Overwrite` | `fragments`, **`new_schema`** (full field list, ids, types) |
| 2 (append) | `Append` | `fragments` |
| 3 (delete) | `Delete` | **`predicate = 'id = 2'`**, `updated_fragments`, `deleted_fragment_ids` |
| 4 (update) | `Update` | `update_mode = 'rewrite_rows'`, `fields_modified`, `updated_fragments`, `new_fragments` |

So **"what changed" is already in the format** — operation kind, the literal delete predicate, which fields
an update touched, fragment deltas, and schema at create. `versions()` supplies the *when*. Manifests give
path/size/etag, and tags give the human names.

**The missing half is "who", and the reason is a missing join key.** Control events carry the verified
`actor` (`f"user:{token.sub}"`, `endpoints/tables.py:125`) but the emit payload does not carry the version
the mutation produced — except `table_created`, which does (`endpoints/data.py:291`, `"version"`). Lance's
transaction log has no notion of a user, and it should not. So the work is:

1. Stamp the resulting version on **every** mutating control event (rows update/delete, column add/drop,
   merge, compaction, restore), the way `table_created` already does. That is the join key; without it
   "who" can only ever be guessed by timestamp proximity, which is wrong under concurrency.
2. A read endpoint that joins per version: Lance transaction (operation, predicate, fragment/field deltas)
   + control-event actor + tag names pointing at that version + the lineage run id when a medallion stage
   produced it.
3. The lakehouse surface: a commit-log view — one row per version, columns *when / who / operation / what*,
   expanding to the detail (predicate, fields, schema diff at create).

Tasks #65/#66 surfaced versions, tags, manifests and schema. Neither answers "who changed this row, and
what did they change" — that is what this adds, and step 1 is a prerequisite nothing else can substitute.

## Where the long-form evidence lives

`docs/audits/` — the three audits in full (routes + IA, MFE composition, Svelte 5), each with its
adversarial verification pass appended. They were written to a scratchpad first, which would have lost them;
a claim like "26 routes map 1:1" needs the table behind it to be worth anything.

## Condition 1 — the MFE + Svelte 5 halves (adversarially verified)

Three audits ran in parallel, each re-checked by a second agent whose default verdict was REFUTED unless
the code itself carried the claim. Outcome: **MFE 5/5 top claims confirmed, routes 8 of 9 confirmed
(1 downgraded), Svelte 5 confirmed-with-corrections** — the verifier refuted 3 of the Svelte report's
sub-claims, which is the point of running it.

### MFE composition

- **Dead cross-zone links (BUG, fixed `bf00499`).** Five `<a>` on pre-merge roots. The verifier
  re-reproduced the 404s on a fresh server rather than trusting the first pass, and confirmed the
  enumeration is complete (a wider grep over single quotes, `{'…'}`, component props and `goto()` found
  the same five and no more).
- **The cross-zone verifier could not start (BUG, fixed `1cd9329`).** Its readiness probe was itself one
  of the dead paths. Two escape hatches were tried and both closed: no `set -e` (refuted — `fail()` exits
  explicitly) and a possible 308 from the login gate (refuted twice — it is 302, and `isGatedPageRequest`
  needs `accept: text/html`, which a bare curl does not send).
- **Nothing composes all four zones automatically (DEVIATES).** `frontend/package.json:13` `dev` runs
  `turbo run dev dev:proxy`, so the proxy exists — but `dev:proxy` appears in no test, config or workflow,
  and `e2e_stack.sh:110` deploys with `--set frontend.enabled=false`. The single-origin composition is
  therefore only ever exercised by hand. This is what made the dead links invisible in aggregate.
- **The zone images are never built in CI (DEVIATES, verified independently).** `make frontend-images` /
  `.docker/frontend.dockerfile` are invoked by nothing automated: the only two `docker build` matches in
  `.github/workflows/*.yml` are prose inside comments. Four dockerfiles sit on the deploy path with no
  automated build. They DO build by hand — see the cluster evidence above — but a break would reach main.

### Svelte 5

- **A stale prop mirror (BUG, fixed `dff061a`).** `search-settings.svelte` copied `weightPct` into local
  `$state` and synced back with an `$effect`, so a saved view's balance was displayed wrongly and then
  overwritten. Now derived from the prop with callback writes. The `svelte-runes` skill's own
  `effect-vs-derived.svelte` example names this anti-pattern verbatim; the MCP autofixer reports zero
  issues on the result and on every other `.svelte` this session touched.
- **The verifier refuted 3 of the report's claims, and it was right to.** Two of the five `$effect`s the
  report wanted deleted (`filter-popover.svelte:126-129`, `search-bar.svelte:119-123`) are
  options-validity clamps driven by a `$derived` options list, not change-detection — the prescribed
  "delete all five" would have regressed both. `LayerPanel`'s guard was graded a bug for having "no
  explanatory comment"; it has a five-line one at `:14-18`. Both downgraded to deviates-with-reason.
- **`TableDetail.svelte:331` — one `$effect`, 60 assignments (DEVIATES-WITH-REASON, not fixed).** It
  resets every editor field when the `table` prop changes, and its comment names the bug that motivated it
  (an editor opened on A surviving into B, so Save writes A's draft to B — audit 2026-07-16). The intent
  is right and the direction is safe (it clears scratch fields; it cannot clobber a parent value the way
  the media bug did). The mechanism is the problem: the invariant is hand-maintained, so a new `$state`
  field that nobody adds to the block silently reintroduces the leak. Recommended follow-up, deliberately
  NOT done in this pass: `{#key table}` at the call site, which re-instantiates the component and deletes
  the whole block. That is a real refactor of a 1000-line component under 191 e2e tests and does not
  belong in a bug-fix wave.
- Runes hygiene otherwise clean: 135 component-tag `bind:` directives, 0 binding to a non-`$bindable`
  prop (re-counted by AST, not regex — the report's 133 was an undercount); 253 `.svelte` × client+server
  plus 18 `.svelte.ts` compile with 0 diagnostics.
- **MCP autofixer, all 9 `.svelte` changed since the pull** (`git diff --name-only e489f2b..HEAD -- '*.svelte'`):
  clean on 8. `top-navbar.svelte` was re-run AFTER the clipping fix, not just before it. The 9th,
  `lineage/datasets/[name]/+page.svelte`, returns 4 suggestions about calling `load`/`setInterval`/
  `clearInterval` inside an `$effect` — all four are heuristic false positives and the verdict is
  **conforms**: `:63-68` is a polling effect that captures `name`, loads once, sets an interval and
  `return () => clearInterval(timer)`, which is the `svelte-runes` skill's own "✅ CORRECT: $effect with
  cleanup" shape. The tool hedges its own suggestion ("ignore if you are sure this function is not assigning
  any stateful variable"). Worth contrasting with the media bug, which had no cleanup and no side effect —
  it was derived state written by an effect, the one thing an effect must not be used for.
  `TableDetail.svelte`'s 60 suggestions are one pattern, judged above, not 60 defects.

## Condition 3 — IA judged against the Lakekeeper console

Route parity was already proven (26 pre-merge → 26 lakehouse, set difference empty both directions;
recomputed from git by the verifier: 34/34 pages). Their console's route set was read directly from
`lakekeeper/console`'s `pages/**`; what could NOT be verified is stated as such in the audit file.

**Where theirs is better** (8 gaps, each grep-verified against ours): soft-deleted objects as a
first-class view with time-bounded undrop (we have no undrop surface at all — our `restore` is Lance
*version* restore, a different thing); **roles** as a managed, nestable object between principal and grant
(ours is tuple-level only); an identity/user directory and profile; server settings + bootstrap +
dependencies + license (our #112, owner-deferred); **per-object** task/queue visibility (ours is
estate-global, so "what is queued for THIS table" is unanswerable); `health` and `files` tabs on table
detail; views and generic tables as distinct object types; and **nested namespaces** (ours are flat
medallion tiers).

**Where ours is better**: lineage as a whole area including column-level lineage (7 routes, no analogue in
their tree); a model registry with a promotion pipeline; an authorization *workbench* rather than a
per-object permission tab — Graph explorer, raw tuple browser, live Check simulator, compiled model; a
compliance audit trail with resource-pivot jump links; event-plane ops (live control events, JetStream
consumer lag, DLQ replay); and a row-level write surface on table detail.

**The one recommendation**: make the warehouse and namespace **detail** pages the hierarchy's landing
surfaces and delete the two P0 scaffolds behind them. `/lakehouse/data` is still an 8-line scaffold whose
text names the deleted `apps/web`, and it is the zone's landing target (`routes/+page.ts:7` redirects
there, `nav-config.ts:236` points at it); `/lakehouse/admin` is the repo's only orphan page — a precise
grep for inbound links returns three Playwright `toHaveCount(0)` assertions and zero product references.
Lakekeeper has no such intermediate: `/warehouse/[id]` IS the surface. Not fixed in this pass because
"what should the data landing page be" is a product decision, not a defect with one right answer.

## Dapr coverage for the merged services (owner question)

**Verdict: nothing is missing, and the absences are a design boundary rather than an oversight.**

Sidecars ARE wired (`chart/templates/media.yaml:43-49`): `dapr.io/enabled`, `app-id`, `app-port`,
`log-level`, and `dapr.io/config: lance-tracing` — so viewer/search/annotator spans join the estate's
distributed traces.

Correctly absent, each verified rather than assumed:

- **No `dapr.io/app-token-secret`.** That token exists only to authenticate *Dapr-delivered* routes.
  `services/common/dapr_auth.py` states the threat: pub/sub events arrive on the same FastAPI app as the
  public API, so without it any client reaching the port could POST a forged CloudEvent and poison the
  lineage graph. Only the services that RECEIVE deliveries enforce it (compaction, lineage, medallion).
  Viewer/search/annotator subscribe to nothing, so there is no delivered route to protect — the
  annotation would inject an unused env var.
- **Not in the `lance-secrets` scopes.** They do not read secrets through Dapr at all (zero hits for
  `SECRETS_FROM_DAPR`); the catalog bearer arrives as a k8s Secret via `secretKeyRef`
  (`media.catalogToken`). Scoping them in would grant reach they never use — and an unscoped store
  fail-closes pods, which already bit this estate once.

**Forward-looking gap (not a defect):** the annotator emits NO event when an annotation is saved. For the
active-learning loop (label a few → retrain → re-predict) that write is exactly the trigger a deriver
would subscribe to; today it is silent, so any loop would have to poll. When active learning lands it
needs a pubsub scope AND the app-token annotation, because the annotator would then receive deliveries.

## The micro-frontends are outside Dapr entirely (#124, owner's second framing)

The owner's follow-up — *"then you know we are missing cache, kv and state management or actor in the
micro-frontend right, to improve ux"* — is a **different finding** from the backend one in
`docs/DESIGN-interactive-state.md`, and it is sharper. That doc argued the services have no operational
state model. This is about the zones themselves, and it is not a design opinion but a measurement:

```
$ kubectl get pods            # containers per pod: 2/2 = Dapr sidecar, 1/1 = none
   lance-ns-catalog-…          2/2      lance-ns-web-annotator-…   1/1
   lance-ns-lineage-…          2/2      lance-ns-web-home-…        1/1
   lance-ns-viewer-…           2/2      lance-ns-web-lakehouse-…   1/1
   lance-ns-search-…           2/2      lance-ns-web-media-…       1/1
   lance-ns-annotator-…        2/2

$ grep -cE "dapr.io/" chart/templates/frontends.yaml
   0
```

Every backend pod has a sidecar. **No frontend zone has one, and the chart never asks for one.** So it is
not that the zones use Dapr badly — they *cannot* use it at all. No state store (hence no KV and no
server-side cache), no subscribe (hence the 15 `setInterval` timers), no actors, and no service invocation:
each BFF reaches backends by direct ClusterIP HTTP.

That matters more for the frontend than for a service, because the zone BFF is the one place in this estate
that is both **inside** the cluster and **holding the user's identity** (the sealed `lance_session` cookie
and the forwarded OIDC bearer). It is the natural home for a per-user cache and for cross-zone shared
state — the sealed session already spans zones, so the mechanism exists and nothing else rides it.

The half that is *not* obvious, and the reason this is not a one-line chart change: a cache in a BFF is a
cache of **authorized** results. Every backend read is FGA-gated per user, so a key that omits the identity
turns a performance win into a tenancy leak, and `/v1/events` — the one change feed that exists — is gated
on `can_observe_events`, i.e. estate admin, so a BFF that subscribed with a service credential and fanned
out to users would have bypassed that gate. The design is being produced with that adversarial half
explicit rather than assumed; the recommendation lands in this section when it is.

## Notifications and progress tracking — which Dapr component, and what we already have (#125)

The owner asked: *"notifications system is missing, like if we want to track stuff and progress. Is pubsub
something we could do with nats for better ux for frontend, or what is right dapr component here?"*

**Pub/sub over NATS is right, and it is not a decision — it is already what this estate runs.**
`chart/templates/dapr-component.yaml` is `type: pubsub.jetstream` against the in-cluster NATS. But pub/sub
is only one of the four pieces, and using it alone would build a notification system that loses
notifications.

### The hard part is already solved once here — copy it, don't invent it

The non-obvious problem with pushing events to browsers is *which replica gets the message*. Dapr's default
is competing-consumer: with a `queueGroupName`, one replica per app-id receives each message, so a user whose
stream lives on replica 2 never sees an event delivered to replica 1. This repo already has the fix, for the
catalog's control events, and the chart says so in its own comment:

> `# BROADCAST component … with NO queueGroupName → jetstream sets no DeliverGroup, so EVERY catalog replica`
> `# receives EVERY event and appends it to its per-replica ring buffer (GET /v1/events).`

That is exactly the semantic a notification stream needs. It is also the opposite of what the movers use, and
the chart explains why both exist. So the pattern to follow is `catalog-control-pubsub`, deliberately, rather
than the shared lineage component.

### Why pub/sub alone would be the wrong answer

That same component is **deliberately ephemeral** — no `durableName`, `deliverPolicy: new` — and its comment
is explicit that the buffer is *"a live-refresh hint window, not a log"*. That is correct for a refresh hint
and wrong for a notification: "your export finished" must survive the user being offline, and an unread count
is state, not an event. Pub/sub delivers the nudge; something durable has to hold the inbox.

### The component set, and what is actually missing

| Piece | Component | Status |
| ----- | --------- | ------ |
| "Something happened" nudge | pub/sub, jetstream, **broadcast** variant | **Have it** — `catalog-control-pubsub` is the template |
| Durable per-subject state: saved views, settings, an inbox | **state store (KV)** | **Have it, live** — `kubectl get components.dapr.io` lists `lance-statestore`, `state.postgresql` on `lance-ns-age-0`, DSN resolved from OpenBao through `lance-secrets`. Round-tripped write/read/delete; an app outside `scopes` was refused |
| Unread counts that cannot race; expiry without a sweeper cron | **actors** (one per user inbox) + **reminders** | **Not built.** The gate is open — `actorStateStore: "true"` is set on the component above — but no actor type is registered |
| Progress of a long job | **workflow** | **Not built, and not needed for #125.** `GET /runs` already carries START/RUNNING/COMPLETE/FAIL with `progress_done/total` and `error_message`. Workflow earns its place when a *saga* needs resuming (annotation publish, #122 `S5`–`S10`), not for reading progress |
| Delivery to the browser | zone BFF subscribes, streams via `query.live` | **Still true that the zones have no sidecar**: `kubectl get pods -o custom-columns=…containerStatuses[*].name` shows all four `web-<zone>` pods running a single container. What shipped instead: the zone's BFF calls the **catalog**, which has the sidecar and owns the store. The identity stays in the session cookie and never leaves the BFF — see `frontend/…/media/src/routes/capi/v1/user-state/[document]/+server.ts` |

### "We don't need JetStream if there is more native Dapr tooling" — the owner's follow-up

Two halves, and they land differently.

**For pub/sub there is nothing more native to reach for.** Dapr pub/sub *is* the native tooling; JetStream
is only the broker behind the component, and the application code cannot tell. Swapping the broker changes
zero lines in `core/control_emit.py` or `api/dapr.py`. So there is no JetStream decision to revisit here —
the "more native" thing is the pub/sub API, which is already what we use.

**For the KV half the owner is pointing at, there is a real choice, and NATS is the wrong side of it.**
Dapr *does* ship a `JetStream KV` state store, so everything could in principle stay on NATS. But per the
[supported state stores reference](https://docs.dapr.io/reference/components-reference/supported-state-stores/)
it is **Alpha and does not support actors** — and actor support is exactly the `actorStateStore: "true"`
flag that gates actors *and* workflow, because Dapr Workflow uses the actor framework internally (Dapr
skill, `dapr-statestore.md:23`). Choosing JetStream KV would buy the durable inbox and then dead-end at the
two building blocks that make progress tracking good.

**The pick that needs no new infrastructure is Postgres.** `state.postgresql` is **Stable** with actor
support in both v1 and v2 — and we already run Postgres: `lance-ns-age-0` is live, and it is what
`LINEAGE_DATABASE_URL` points at. So the whole missing layer is *one component* aimed at a database that is
already deployed, backed up and monitored. No Redis, no extra pod, no new failure domain. The Dapr skill's
example uses Redis only because `dapr init` installs Redis in a container; it is not a recommendation.

| Option | Actors / workflow | New infrastructure |
| ------ | ----------------- | ------------------ |
| `state.jetstream` (KV on the NATS we already run) | **No** — Alpha, no actor support | None |
| `state.redis` (the skill's example) | Yes, Stable | A Redis to run, secure and back up |
| **`state.postgresql` on `lance-ns-age-0`** | **Yes, Stable (v1 and v2)** | **None** |

### The trap to avoid

`GET /v1/events` is gated on `can_observe_events`, i.e. **estate admin**. A per-user notification stream must
not reuse that feed or a service credential to fan out from it — that would bypass the gate for every
non-admin. Notifications are written *for a subject*, so the BFF reads only that subject's key and the admin
gate never enters the path. This is the same failure mode as a BFF cache keyed without the identity.

So: one root cause again (#124), and notifications were the clearest user-visible reason to fix it.

**What that reasoning got right and what it got wrong.** The state store was the right root cause and it is
now live on Postgres exactly as argued. But the conclusion that notifications were *blocked* on it was
wrong, and I only found that out by reading `services/lineage/…/schemas.py` — which the owner had to tell me
to do. `RunStatus` already modelled the whole lifecycle, so #125 shipped against `GET /runs` with **no** new
component, no inbox and no workflow. The KV inbox is still the right home for *read / dismissed*, which is
per-subject state the run feed cannot carry; it is not what made the feature possible.

## Outstanding

Superseded by the ledger at the top of this file — keep the two lists from drifting apart by editing that
one. Two items that stood here are now closed, with their evidence:

- **Condition 5 re-drive, closed.** The frontend changed under the earlier evidence (navbar zone-root row,
  five repointed links, the media Settings fix), so it was re-driven against the shipped code:
  `scripts/verify_cross_zone_oidc.mjs` now runs **21 checks** ending `✓ cross-zone OIDC + per-user authz
  PROVEN`, with a screenshot per condition in `docs/audits/shots/` (13 files).
- **CI, closed.** The `7605b2f` run is `completed/success` on **all six jobs** — `frontend`, `test`,
  `ray-e2e`, `lineage-e2e`, `e2e-stack`, `auth-e2e`. The `e2e-stack` job that was under watch is green.

**All four zone Playwright suites are green** (home 5, lakehouse 190/190, media 2, annotator 8) with
`--retries=1 --workers=8`; every turbo task (43) and every Python gate (972 tests, ruff, ty, openapi
drift, prod-render) is green.

## Note on the subagent failures

Four workflow runs died on provider **529 Overloaded** — twice after real work (266 and 260 tool calls),
twice instantly with zero. Their output was recovered by hand: the zone-contract fix and the whole
lineage track (972 unit tests green, ty and ruff clean). Everything since is main-loop work.

## Honest fractions per condition — the closing statement

Written at the goal's own stop point (it says: past 45 turns, stop and summarize rather than thrash). Every
row cites something checkable — a file in this repo, a commit, or a screenshot in `docs/audits/shots/`.
Nothing here rests on "looks right".

| # | Condition | Fraction | Where the evidence is |
| - | --------- | -------- | --------------------- |
| 1 | Architecture verified against the skills | **3/3 halves** | turbo.json: the audit table in this file, with cache correctness proven empirically both directions (unchanged → `1 cached >>> FULL TURBO` 20ms; one input byte → `0 cached` 162ms; reverted → cached, tree clean). MFE: `docs/audits/2026-07-26-mfe-composition.md` (1027 lines, 5/5 top claims confirmed by a second pass). Svelte 5: `docs/audits/2026-07-26-svelte5.md` (753 lines) + the MCP autofixer on **all 9** `.svelte` changed since the pull, with the one non-clean file judged and recorded as *conforms* |
| 2 | Toolchain migration complete | **complete, gate proven both ways** | 3 defects fixed (`d28a334`, `ffcfcaa`, `7df035d`). The mutate-and-watch-it-fail proof: `lint` → `eslint .` gives *"expected 'eslint .' to be 'oxlint .'"*; DELETING `fmt:check` gives *"expected undefined to be 'rsvelte-fmt --check .'"*; restored → 79/79, tree clean |
| 3 | Zones, routes, IA | **complete** | `docs/audits/2026-07-26-routes-and-ia.md` (770 lines): every route in all four zones enumerated; 26 pre-merge → 26 post-merge with the set difference empty **both** directions, recomputed from git by the verifier (34/34 pages); one orphan found (`/lakehouse/admin`, zero product-code inbound refs); Lakekeeper comparison with 8 gaps, 6 advantages and one recommendation. 8 of 9 claims confirmed, 1 downgraded |
| 4 | media/annotator split | **complete** | Backends separate, read off the LIVE pod env not the template: media = `ANNOTATOR_API SEARCH_API VIEWER_API`, annotator = `ANNOTATOR_API VIEWER_API` (no SEARCH_API). Reuse quantified: 4 of 5 `@repo/*` shared, `@repo/engine` annotator-only. Pixi recommendation + bundle consequence in the condition-4 section above |
| 5 | Cluster TODO discharged | **37 of 37 — 35 ticked, 2 struck with the reason** | `docs/TODO-CLUSTER-VERIFY.md`, each box carrying its evidence. Live drive: 17 checks green + 12 screenshots in `docs/audits/shots/`. The 2 non-ticked boxes are STRUCK with the reason rather than left ambiguous: the annotator runner chip, where driving it surfaced the viewer OOM instead — a finding that mattered more than the chip and is recorded as #121 |
| 6 | Green and pushed | **complete** | `pytest tests/unit` exit 0; `ruff check` + `format --check` (361 files); `ty check` all-clean; `make openapi` no drift; `prod_render_check.sh` green; `turbo run check test lint fmt:check build` **43/43 with 0 cached** (`--force`); all four Playwright suites (home 5, lakehouse 191, media 2, annotator 8); no untracked or husk directories; CI read to completion — the `5dbf643` run completed **success across every job** |

### The defects this pass actually found

Ten, all fixed and pushed, each with a test that fails without the fix: five dead cross-zone links
(`bf00499`), a verifier that could not start because its own probe was one of those dead paths
(`1cd9329`), an FGA batch-write that silently dropped sibling grants (`363de65`), a bundle gate measuring
deferred bytes as entry cost (`56a6aad`), a security test red on 3% of runs (`5d4d1d8`), a stale prop mirror
displaying a fusion balance the search was not running (`dff061a`), a navbar clipping regression **I
introduced and a screenshot caught** (`bd8a1cb`), a 500 that should have been a 400 (`60d873f`), two
unauthenticated gateway doors unasserted in the prod render (`5c12b96`), and an annotator header whose
account avatar sat on the left because the zone hand-rolls the shell (`2d9ca95`).

### What is NOT done, and why

Rewritten 2026-07-26 — most of what stood here is now closed, and leaving the old list up would have been
the exact drift this file exists to prevent. What is genuinely still open:

- **#119** `TableDetail.svelte:331`'s 60-assignment reset effect. Deviates-with-reason: intent right,
  mechanism hand-maintained. The fix (`{#key table}`) re-instantiates a 1000-line component under 191 e2e
  tests and belongs in its own pass. This session gave the reason teeth: I edited that same component to
  add a conditional column and **dropped 6 of its 10 history versions** (`missing: 9, 8, 7, 5, 4, 3`) with
  `svelte-check` at 0 errors. It is a component that punishes casual edits.
- **#122** annotation projects: designed in full, built only as far as #124 allows. Slices `S1`–`S4` need
  no store and are the next buildable unit; `S5`–`S10` need actors, which are unregistered.
- **#124's second half**: no actor type, no workflow. The store they stand on is live.
- **#103** media plane on the governed warehouse — corpus as registered project tables rather than
  hostPath. Predates this goal.
- `/lakehouse/data` is still a P0 scaffold and it is the zone's landing target; `/lakehouse/admin` is an
  orphan. Both are product decisions, not defects with one right answer.

Closed since this list was written, each in the ledger with its evidence: **#113** (live, 101 paths, all 10
versions, alice 200 / bob 403), **#114** (pylance 9, `e7c0504`), **#117** (OpenCV count 0, `fd787cd`),
**#118** (`ci.yml:146`), **#120**, **#121** (0 restarts, `629b1b1`), **#123** (decided: a URL, no GPU in
node capacity), **#125** (`3000ba4`), **#102** (13 timers → 1, gate-enforced).

### The UX track added ten more, in already-pushed code

The ten above came from verifying the pull. The twenty-condition UX pass that followed found ten more, and
the ones worth naming are the ones that had already shipped green: an **anonymous 6.6 MB atlas read** in two
zones at once (trivially exploitable by any signed-in-or-not caller, closed by `requireSession` in
`bff.ts`); a caller-supplied `v` that could **fork the server cache** — six junk tokens evicted the product
entry; a `cache-control: public` on a per-identity response; `Restore.version` **overwriting the row's own
primary key** in the history endpoint; a notification panel where the first failure sat at **position 445**
so no failure could ever be seen, and whose error then rendered a 25-line stack trace over the whole panel;
a `| default 255` that rendered 255 for an explicit `0`, making a config change look applied while nothing
moved; and my own conditional-column edit dropping 6 of 10 history versions.

Two adversarial workflows returned **4/4 REFUTED** on claims I had already called proven. That is the
number that matters: the gates were green for all of them.

### The honest lesson

The audits caught the dead links, the batch-write bug and the runes bug. They did **not** catch the navbar
alignment, the duplicated shell header, or the annotator's 502 — the owner looking at the product caught the
first two, and driving it in a browser caught the third. The annotator's own 8 Playwright tests passed
through all of it, because they mock the APIs on a dev server. That is the argument for the browser drive
existing at all, and the reason "every gate green" is a floor rather than a finish.
