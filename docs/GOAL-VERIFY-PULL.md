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
| 4 | media/annotator split sound and documented; Pixi recommendation | **backend DONE** (live pod env). Bundle numbers + Pixi verdict OUTSTANDING |
| 5 | The cluster TODO (`docs/TODO-CLUSTER-VERIFY.md` §1–6) discharged | **essentially DONE** — see the evidence table |
| 6 | All gates green, stale dirs deleted, pushed, CI confirmed | **blocked**: 16 lakehouse e2e failures (self-inflicted, below) |

## Conditions the owner added mid-flight

| Added | What | Task | Status |
| ----- | ---- | ---- | ------ |
| Lineage track | OpenLineage spec fidelity; Dapr/FastAPI/Ray test coverage; Marquez parity; gold JSONB-in-Lance | #111 | Agent work salvaged; gold finding landed. Spec/coverage/parity reports partial |
| Dapr sweep | Is Dapr missing anywhere in the lance-audio merge (viewer/search/annotator)? | — | **DONE — nothing missing**; see below |
| Git-like data history | Answer "what changed, by whom, when" from Lance transactions/manifests/tags+branches, Lakekeeper-style | #113 | NOT STARTED |
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
| **Gold never embedded JSONB lineage** | Docs, seed and demo header all described behaviour the product does not have. Stale, not dangerous: the only reader is disabled | (lineage track, uncommitted) |
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

## turbo.json audit (condition 1)

Cache correctness proven **empirically, both directions**: unchanged → `1 cached >>> FULL TURBO` (20ms);
one input byte changed → `0 cached` (162ms); reverted → cached again, tree clean.

The two failure modes the turborepo skill flags are both absent, and that is load-bearing:
no `incremental`/`composite` anywhere (so `check` with `outputs: []` is correct), and **zero
`$env/static` usage** (so nothing is baked at build time and a cached bundle cannot carry stale env).
`globalPassThroughEnv` carries CI + PLAYWRIGHT_* — the skill's own fix for strict-mode filtering.
Two defensible deviations: `.svelte-kit/**` in outputs (the budget gate weighs `output/client`, so it
must be restored) and `test → build` per package (the transit-node pattern would parallelise better).

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

1. **16 lakehouse e2e failures — self-inflicted** by the navbar restructure. Specs assert the old
   trigger set. Mine to fix; no push until green.
2. Lakekeeper console comparison + orphan-route sweep (condition 3).
3. Pixi bundle numbers + recommendation (condition 4).
4. Dapr coverage sweep for viewer/search/annotator.
5. Lineage track: spec-fidelity, seam coverage and Marquez-parity reports (gold finding already landed).
6. Push + read CI green.
7. Then the newly added build work: git-like data history (#113), Lance OTel (#114).

## Note on the subagent failures

Four workflow runs died on provider **529 Overloaded** — twice after real work (266 and 260 tool calls),
twice instantly with zero. Their output was recovered by hand: the zone-contract fix and the whole
lineage track (972 unit tests green, ty and ruff clean). Everything since is main-loop work.
