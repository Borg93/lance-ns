# Goal: verify the claude.ai pull for real — live tracker

The pull (25 commits, `3f17543..e489f2b`) was written in a sandbox with **no docker, kind or helm**.
Everything in it was unproven against an image, a chart or a cluster. This file is the single place the
goal, the conditions the owner added mid-flight, the evidence, and what is left all live — so none of it
is carried in conversation memory alone.

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
| 1 | Architecture verified against the skills (turbo.json, 4-zone MFE, Svelte 5) | **turbo.json DONE** (audit table + cache proof below). MFE/Svelte partial |
| 2 | Toolchain migration complete (no eslint/prettier; identical scripts; gates real) | **DONE** — 3 defects found and fixed |
| 3 | Zones/routes/abstractions right; judged against the Lakekeeper console | **structural half DONE** (26→26 exact diff). Lakekeeper comparison + orphan sweep OUTSTANDING |
| 4 | media/annotator split sound and documented; Pixi recommendation | **DONE** — backends separate (live pod env), reuse quantified (4 of 5 `@repo/*` shared), Pixi verdict written, and the bundle-budget gate it exposed is fixed + tested |
| 5 | The cluster TODO (`docs/TODO-CLUSTER-VERIFY.md` §1–6) discharged | **essentially DONE** — see the evidence table |
| 6 | All gates green, stale dirs deleted, pushed, CI confirmed | **DONE** — every gate green, pushed `e489f2b..f8f1480`, CI `test` job green, rest under watch |

## Conditions the owner added mid-flight

| Added | What | Task | Status |
| ----- | ---- | ---- | ------ |
| Lineage track | OpenLineage spec fidelity; Dapr/FastAPI/Ray test coverage; Marquez parity; gold JSONB-in-Lance | #111 | Agent work salvaged; gold finding landed. Spec/coverage/parity reports partial |
| Dapr sweep | Is Dapr missing anywhere in the lance-audio merge (viewer/search/annotator)? | — | **DONE — nothing missing**; see below |
| Git-like data history | Answer "what changed, by whom, when" from Lance transactions/manifests/tags+branches, Lakekeeper-style | #113 | **Feasibility PROVEN against pylance 8** — see the section below. The format supplies what/when; the blocker is that mutating control events do not stamp the resulting version, so "who" has no join key |
| Lance OTel | Wire Lance's own observability into our OTLP→Collector→GreptimeDB path | #114 | NOT STARTED |
| Navbar IA | Four triggers: Lakehouse (incl. lineage + admin), Search, Annotate, Compute (after rask) | — | **DONE** — Compute deliberately unrendered until the zone exists |
| Settings surface | Break out auth / authz / audit into their own surface | #112 | Deferred by owner ("keep it as is") |

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

## Outstanding

1. Lakekeeper console comparison + orphan-route sweep (condition 3).
3. Lineage track: spec-fidelity and Marquez-parity reports (gold finding + Dapr-delivery/spec-conformance
   tests already landed in `b43b8ff`).
4. Confirm `e2e-stack` goes green on `363de65` (every other job is already green: `test`, `frontend`,
   `auth-e2e`, `lineage-e2e`, `ray-e2e`).
5. Then the newly added build work: git-like data history (#113), Lance OTel (#114).

**All four zone Playwright suites are green** (home 5, lakehouse 190/190, media 2, annotator 8) with
`--retries=1 --workers=8`; every turbo task (43) and every Python gate (972 tests, ruff, ty, openapi
drift, prod-render) is green.

## Note on the subagent failures

Four workflow runs died on provider **529 Overloaded** — twice after real work (266 and 260 tool calls),
twice instantly with zero. Their output was recovered by hand: the zone-contract fix and the whole
lineage track (972 unit tests green, ty and ruff clean). Everything since is main-loop work.
