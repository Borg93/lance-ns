# Goal: reactive, stateful frontends — the UX track

Set 2026-07-26 after the owner said, fairly, that asking what to do next instead of finishing is the
problem. This is the goal I will work without further questions, and the conditions are what "done" means.
Every condition names its own evidence, because the standing rule is that a claim cites command output or a
screenshot.

The parent tracker is `docs/GOAL-VERIFY-PULL.md`; its ledger links here. This file is the working list.

## Why these, and not other things

Three measurements, already taken, decide the order:

- `/media/api/atlas/points` is **6,678,928 bytes**, and a browser refresh or a second user pays it in full.
- **15 files** poll with `setInterval`; `query.live` is used in exactly one. So two panels on the same
  entity can disagree, and a mutation in one does not refresh another until a timer fires.
- The lineage service already serves `GET /runs` (START→RUNNING→COMPLETE/FAIL with progress and error) and
  `GET /events?after=` (governed per subject, keyset cursor). **The backend for notifications exists.**
  What does not exist, by grep, is any notification surface at all.

## Conditions

| # | Condition | Evidence that closes it |
| - | --------- | ----------------------- |
| 1 | **The history endpoint is actually deployed.** `#113`'s view was built against a contract; the running catalog predates the endpoint by 81 minutes | `curl /openapi.json` on the live pod lists a `history` path, and the view renders real versions in a browser as alice, screenshotted |
| 2 | **Live feeds survive.** nginx severs an idle stream at 60s and SvelteKit's SSE emits no keepalive, so `query.live` at scale would be *worse* than polling | `proxy-read-timeout` on the Ingress, and a feed observed open past 60s |
| 3 | **Notifications exist** — REFUTED once, partly fixed. The bell marked runs read it never showed (13 marked, 8 rendered, the FAIL buried) and clipped its descenders; both fixed in `ef97e01`. The zone-mount defect the verifier found is still open. A run that starts, finishes or fails is surfaced without the user hunting for it, in every zone, from `/runs` — no new backend | Drive a real cascade run as alice; screenshot the surface showing START then COMPLETE/FAIL with its error text |
| 4 | **The timers are gone.** `setInterval` replaced by `query.live` on the lineage cursor | `grep -rl setInterval` per zone, with a stated reason for any survivor |
| 5 | **User work persists.** The workflow graph and saved views leave `localStorage` for the state store, per subject | Write in one browser context, read it in a fresh one — proven, not asserted |
| 6 | **The expensive read is cached server-side** — REFUTED once, fixed in `91a472d`: a caller-supplied `v` forked the cache without bound (20 junk tokens = 20 extra 6.6 MB reads, shared entry cold, single-flight defeated), and the anonymous read was still open one URL away at `/annotator/api/atlas/points`. Needs a re-drive. Redis, authorize-every-request, keyed on `(resource, version)`, single-flight | A second user's first atlas load serves from cache; a user without access still gets 403 |
| 7 | **Green and pushed.** Every gate, cold | Python 1173+, whole-repo `ty`, `ruff services tests`, all four zone suites, `turbo --force`, prod-render, CI read to completion |

## Conditions 8–12: the standing rules, as conditions rather than good intentions

The owner's point: these were agreed and then quietly skipped. They are conditions, not preferences, and a
condition above is **not** closed until these hold for the work that closed it.

| # | Condition | Evidence that closes it |
| - | --------- | ----------------------- |
| 8 | **Redeployed, not just unit-green.** A change that only passes tests has not been verified — the bug class is the never-driven union (auth + FGA + the real image). Every backend or chart change is rebuilt, `kind load`ed, pods **deleted**, and the pod's imageID digest confirmed to have changed | The digest before and after, plus a behaviour that changed because of it |
| 9 | **Driven in a browser with Playwright, as alice and as bob.** Not the dev server with mocked APIs — the real ingress on `:8090` with a real Dex login. The annotator's own 8 tests passed through a 502, a clipped navbar and a mislaid avatar, because they mock | A drive script per surface, its output, and screenshots in `docs/audits/shots/` |
| 10 | **Screenshots opened and described.** A screenshot nobody looks at is a file, not evidence. Looking has caught four defects this session that every passing assertion missed | For each: what I saw, including anything wrong that I did not set out to check |
| 11 | **Skills invoked and read, not skimmed** — writing-python, fastapi, testing-python, svelte-5 plus the svelte MCP autofixer on every touched `.svelte`, turborepo, micro-frontends, dapr, openfga | The autofixer's actual output per file, and for each skill used, the reference file read and what it changed |
| 12 | **The tracker stays true.** Every ask has a row with an honest state; nothing is marked done that was not driven | `docs/GOAL-VERIFY-PULL.md`'s ledger current at the end |

## Condition 13: EVERY open task disposed of explicitly

Not "finish everything" — **decide** everything. Each row below ends the goal either done-with-evidence or
struck with a stated reason, so none can quietly rot. This list was built by diffing the goal against the
task tracker, because the first draft of this file silently omitted six of them, including a whole
ten-condition goal.

| Task | Disposition — evidence, or the reason it is struck |
| ---- | -------------------------------------------------- |
| `#102` reactive data flow | **DONE.** 13 timers → 1 per zone, gate-enforced: `home 0 · lakehouse 3 · media 1 · annotator 0`, where lakehouse's 3 are two prose mentions plus one justified survivor and media's 1 is justified. `poll-reason.test.ts` fails on any unexplained timer (`8bbdb61`) |
| `#113` git-like history | **DONE.** Live: `/v1/table/{id}/history` in the running catalog's OpenAPI (101 paths), all 10 versions rendered, the delete predicate `id = 2` verbatim, alice 200 / bob 403 |
| `#125` notifications | **DONE.** Driven in the lakehouse zone against 891 real runs: bell in the navbar, two Failed rows on top with their errors, five completions below (`3000ba4`) |
| `#117` annotator bundle | **DONE.** OpenCV gone — `grep -c opencv frontend/packages/engine/package.json` → **0**; replaced by `corners.ts` with a golden-file test, net −213 lines (`fd787cd`) |
| `#118` zone images in CI | **DONE.** `.github/workflows/ci.yml:146` — a `zone-images` job builds all four and smoke-runs each container against its own base path (`927ac84`). My first check grepped the wrong pattern and read 0; the job was always there |
| `#121` viewer OOM | **DONE.** 1536Mi/768Mi sized from measured cgroup peaks; 0 restarts under the load that killed it (`629b1b1`) |
| `#123` encoders | **DECIDED, not built, and that is the answer.** A URL, not a Deployment: the servers are stock `vllm/vllm-openai` serving 4.27 GB checkpoints, and this cluster has **no `nvidia.com/gpu` in node capacity**. Wiring proven live (503 → 200). Remaining: one line in the operator docs so it is not re-litigated |
| `#124` state store | **HALF DONE.** The store is live and proven — component loaded, actor state store enabled, write/read/delete round trip, unscoped app refused. Actors for `#122` and workflow for the publish saga are NOT built |
| `#122` annotation projects | **DESIGNED.** `docs/DESIGN-annotation-projects.md`: entities, both state machines, authz doors, publish contract. Slices `S1`–`S4` need no store; `S5`–`S10` stand on `#124`'s actors, which do not exist yet |
| `#111` lineage track | **PART LANDED.** Gold finding + Dapr-delivery tests in `b43b8ff`. Spec-fidelity and Marquez-parity reports outstanding — and `#18`'s real fix (emitting `outputStatistics` from the catalog write path) belongs here |
| `#103` media on the governed warehouse | **STRUCK for this goal.** Corpus as registered project tables rather than hostPath is a data-plane migration, not a UX-track item; nothing in conditions 1–20 depends on it |
| `#100` annotator residuals | **STRUCK — owner-scheduled.** The owner's own words were "user to schedule". Export serializers and a managed taxonomy are new product surface, not this goal |
| `#101` models MLflow parity | **STRUCK — owner-deprioritised** until after the product pass (`#97`) |
| `#86` prod-readiness residuals | **STRUCK as a unit, absorbed in part.** Inherited from a retired tracker; the pieces that mattered this session were done under their own conditions (secrets sole-source, prod-render green, fail-closed on a missing secret proven live). What remains is unenumerated, and enumerating it is its own pass |
| `#119` `TableDetail` reset effect | **STRUCK with reason, and today reinforced it.** `{#key table}` re-instantiates a 1000-line component under 191 e2e tests. I touched this file's column set today and broke six of ten rows; that is the risk profile, and it needs its own pass |
| `#112` Settings surface | **STRUCK — owner deferred** ("keep it as is"). Confirmed still deferred |
| `#20` NATS HA / query engine | **STRUCK — parked by the owner.** Listed so parked stays distinguishable from forgotten |
| `#90` rask merge | **STRUCK — blocked and owner-gated:** never rask main, no rask push, decisions proposed only |
| `#97` PRODUCT-WORKS PASS | **OPEN — the one I am not closing.** A ten-condition goal of its own. Several of its conditions were advanced today (runners, one-nav, lineage facets, gates), but re-checking all ten against the deployed product is a pass, not a line item, and claiming it here would be the padding this goal exists to prevent |
| Storybook | **STRUCK for this goal.** `find -name .storybook` → **0**; not adopted. Two presentation bugs this session were invisible to 191 e2e tests, so the case is real — but adopting it is a tooling pass, and today the screenshot rule caught them instead |
| `/lakehouse/admin` orphan | **RESOLVED — no longer an orphan.** 11 inbound references from zone code today, against zero when it was reported. The IA work re-connected it |
| `/lakehouse/data` scaffold | **OPEN, product decision.** Still the zone's landing target and still a P0 scaffold — visible in today's screenshot as "The Data zone (P0 scaffold)". Not a defect with one right answer |

## Conditions 15–20: what the adversarial pass returned

All four verify agents returned **REFUTED**, which is the pass working rather than failing. Four defects
were in code already pushed; three are fixed (`91a472d`, `ef97e01`). These are what is left, plus the
residuals the agents stated rather than hid.

| # | Condition | Evidence that closes it |
| - | --------- | ----------------------- |
| 15 | **A live stream survives without reconnecting.** `IDLE_TIMEOUT: 255` is a ceiling, not a fix — SvelteKit's SSE emits no heartbeat, so an idle stream still drops at 255s and each reconnect re-primes the whole 200-event window and writes an audit record | A keepalive on the stream, and one observed open past 255s with no reconnect in the access log |
| 16 | **Zone images redeploy too.** Condition 8 said "backend or chart", so the running lakehouse image predated `#113`: the tab bar had no History, `?tab=history` silently fell back to overview, and the agent's own "newest version renders" check passed on a badge beside the title | A digest change per zone image, and the new surface asserted INSIDE its own panel, not on a neighbouring element |
| 17 | **A session-gated 200 must not say `Cache-Control: public`.** `KEPT_HEADERS` passes the upstream's value through verbatim on responses that now require a session. No leak today (no `proxy_cache` on the Ingress) — wrong the moment one is added, which the author's own scaling note recommends | The header rewritten to `private` on gated routes, with a test |
| 18 | **MET, and the diagnosis is the finding.** The column is `—` on every row because the two populations are DISJOINT: a catalog-registered table has this view, but its versions come from catalog operations that emit no `outputStatistics`; the medallion datasets whose producing runs DO carry them (`gold$catalog` v70 = `row_count=8, size_bytes=284`, read live) are storage-managed and have no catalog detail page — the zone says so itself: *"Not a catalog-registered table — storage-managed datasets (medallion zones) have no catalog detail."* | The bar is "never a misleading 0", and `—` with `title="the run that wrote this version measured no output statistics"` is exactly that. **I tried to improve it to a conditional column and introduced a regression**: making `columns` derive on `rows` changed the column identity mid-load and six of ten versions stopped rendering (`missing: 9, 8, 7, 5, 4, 3`). Reverted; all ten render again. The real improvement is to emit the facet from the catalog write path — a backend change, tracked under `#111`, not a UI tweak |
| 19 | **Condition 5 is not closed.** The user-state backend survives active attack (bob cannot read or delete alice's state — proven by inverting the key AND the owner check), but the verifier found an undisclosed data-loss path | The path named, fixed, and covered by a test that fails without the fix |
| 20 | **MET.** Audited every workflow script in this session. A single `parallel()` with no second stage is CORRECT — one fan-out needs no pipeline — so the defect is specifically two sequential `parallel()` calls where the second consumes the first's results. Of the three written this session: `discharge-owner-decisions` already used `pipeline`; `frontend-state-architecture` has one `parallel` feeding a single judge, which is a **justified** barrier because the judge scores four designs against each other; `ux-reactive-track` had `parallel` (line 191) → `parallel` (line 202) reading `built[i]`, and that is the one that cost ~40 minutes | Rewritten to `pipeline()`; the script now shows `parallel:0 pipeline:1`. **The distinguishing test, recorded so it is applied rather than remembered: does stage N need cross-item context from ALL of stage N-1?** Here it did not — each verifier read only its own scope's report, so nothing was shared across items and the barrier bought exactly nothing |

### The screenshot lesson, and a correction to condition 10

Condition 10 said "open the screenshots and describe them". That is **not sufficient**, and this pass
proved it on my own work: I read `notifications-panel-open.png` row by row and reported it correct, while
it was rendering `inqest_events` for `ingest_events` and `aqqreqate_qold` for `aggregate_gold` — every
descender clipped by `truncate` + `leading-none` on a line box 2px shorter than the glyphs (`clientH 14`
vs `scrollH 16`). A reader silently repairs words; it took the verifier a **4× zoom** to see it.

So condition 10 now requires: zoom on text, and where a defect is suspected, measure it in the DOM
(`clientHeight` vs `scrollHeight`) rather than judging by eye.

## Condition 14: the mistakes from 2026-07-26 do not recur

Six defects were introduced or asserted falsely in one session, all by the same habit — acting before
checking. Each gets a guard, and the guard is what closes this condition, not a promise.

| What went wrong | Guard |
| --------------- | ----- |
| **`helm upgrade -f chart/values.yaml` wiped the release.** Every override went — the media plane, auth and runners were deleted from a live cluster. Recovered from revision 49 | Never upgrade from chart defaults. Always `helm get values lance-ns -o yaml > /tmp/v.yaml` first and upgrade with `-f /tmp/v.yaml`. Verify the pod count before and after |
| **A password-bearing DSN was put in a k8s Secret**, which is the exact anti-pattern `services/common/secrets.py` opens by describing as an audit finding | Secrets for app services come from the Dapr secret store (OpenBao) as the sole source. `grep` the chart for a new password or DSN in `stringData` before deploying |
| **The state store was scoped to an app the secret store was not scoped to**, silently disabling actor hosting — the sidecar logged it and nothing failed loudly | The secret store's scopes are now derived from `stateStore.scopes`. After any scope change, grep the sidecar log for `isn't loaded` and `Actor state store not configured` |
| **Notifications were designed without reading `services/lineage/schemas.py`**, where `RunStatus` already carried START/RUNNING/COMPLETE/FAIL with progress and error | Read the code before designing. For any new surface, first grep for an existing model, endpoint and client method |
| **Deleting the OpenBao pod wiped every secret and took the estate down.** It runs `server -dev` — in-memory — and the seed Job runs only on install/upgrade, so a blanket `kubectl delete pod -l instance=lance-ns` destroyed all three secrets and nine pods then correctly fail-closed: `RuntimeError: secret 'rustfs-secret-key' unavailable from Dapr store 'lance-secrets'/'lance' — failing closed (store is the sole source)` | Never delete the OpenBao pod in devMode as part of a redeploy sweep. If it is deleted, re-seed before restarting anything: `bao kv put secret/lance …` with all three keys, then restart the dependents. The fail-closed behaviour is correct and is what made this visible in 90 seconds rather than as corrupted data |
| **I read `containerStatuses[0]` and called three services "SAME"** — index 0 on a 2/2 pod is the Dapr SIDECAR, whose digest is identical across every service, which should itself have been the tell | Read the app container BY NAME (`[c for c in containerStatuses if c.name != 'daprd']`), never by index |
| **The goal itself omitted six open tasks**, including `#97`, a ten-condition goal | Build the task list by diffing against the tracker with a script, not from memory. Condition 13 is that diff |
| **Two false alarms in ten minutes** — the catalog was probed on port 8100 when it listens on 2333, then an idle event buffer was called a broken cursor | Read the service port from the Service object before probing. Distinguish "no data yet" from "broken" before reporting either |

## The polling measured live, 2026-07-26

Evidence for condition 4, taken from the running catalog rather than from the source:

```
167 of 167 requests were /v1/events?since=0     the cursor never advanced
9 requests in 120s                              one poll every ~13 seconds
```

The cursor does not advance because the buffer is genuinely empty — the component is ephemeral with
`deliverPolicy: new` and nothing had happened since the pod restarted. So this is not a broken feed; it is
a **13-second poll of an idle endpoint, forever**, which is precisely the cost condition 4 removes. Note
the endpoint is estate-admin gated (`can_observe_events`), so this feed can never serve a non-admin — the
lineage cursor is the one that can.

## Rules I am holding myself to

- **Read the code before designing.** Three corrections in one session came from not doing this: the
  notification backend already existed, the secret store was already the estate's rule, and `lance-secrets`
  scoping was already documented as a failure class.
- Evidence over assertion; a test that cannot fail is not a test.
- Backward compatibility does not matter — change it to the right thing and update every caller.
- If blocked on the same error three consecutive turns, stop and summarise with exact commands and errors
  rather than thrashing.

## Status

Tracked live in `docs/GOAL-VERIFY-PULL.md`'s ledger. Conditions close here as they are proven.
