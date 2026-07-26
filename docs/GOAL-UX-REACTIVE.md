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

| Task | What it needs |
| ---- | ------------- |
| **`#97` PRODUCT-WORKS PASS** | **A ten-condition goal still in progress and omitted from the first draft of this file**: annotator loop, runners, one-nav, FGA workbench, create-project, preview, lineage facets, drawers, registry, gates. Each condition re-checked against the deployed product and marked done or struck |
| `#102` reactive data flow | Conditions 3–4 above are its implementation |
| `#124` state store / actors / workflow | Store is live and proven. Remaining: actors for `#122` task claims, and workflow for the publish saga |
| `#125` notifications | Condition 3 above is its implementation |
| `#111` lineage track | OpenLineage spec-fidelity and Marquez-parity reports (gold finding + Dapr-delivery tests already landed in `b43b8ff`) |
| `#122` annotation projects | Slices `S1`–`S4` need no store and are buildable now; `S5`–`S10` stand on the state store, which is live |
| `#123` encoders | Decided: a URL, not a Deployment (no GPU on this cluster). Remaining: record it in the operator docs so nobody re-litigates it |
| `#103` media on the governed warehouse | Corpus as registered project tables rather than hostPath |
| `#100` annotator residuals | Export serializer service (COCO/YOLO/CSV/HF) + a managed label taxonomy. Owner said "to schedule" — so schedule it or strike it |
| `#101` models registry MLflow parity | Owner-deprioritised until after the product pass. `#97` is that pass, so this unblocks with it |
| `#86` prod-readiness residuals | Inherited from the retired production-readiness tracker; enumerate what is actually left of it |
| `#119` `TableDetail` reset effect | `{#key table}` under 191 e2e tests — its own pass |
| `#112` Settings surface | Owner deferred ("keep it as is"); confirm it stays deferred |
| Storybook | Two presentation bugs this session were invisible to 191 e2e tests and obvious in a screenshot |
| `/lakehouse/data` scaffold, `/lakehouse/admin` orphan | Product decisions, not defects with one right answer |
| `#20` | **Parked by the owner** — NATS HA via the nats operator, NACK/GitOps, query engine. Stays parked; listed so it is not mistaken for forgotten |
| `#90` rask merge | Blocked and owner-gated: never rask main, no rask push, decisions proposed only |

## Conditions 15–20: what the adversarial pass returned

All four verify agents returned **REFUTED**, which is the pass working rather than failing. Four defects
were in code already pushed; three are fixed (`91a472d`, `ef97e01`). These are what is left, plus the
residuals the agents stated rather than hid.

| # | Condition | Evidence that closes it |
| - | --------- | ----------------------- |
| 15 | **A live stream survives without reconnecting.** `IDLE_TIMEOUT: 255` is a ceiling, not a fix — SvelteKit's SSE emits no heartbeat, so an idle stream still drops at 255s and each reconnect re-primes the whole 200-event window and writes an audit record | A keepalive on the stream, and one observed open past 255s with no reconnect in the access log |
| 16 | **Zone images redeploy too.** Condition 8 said "backend or chart", so the running lakehouse image predated `#113`: the tab bar had no History, `?tab=history` silently fell back to overview, and the agent's own "newest version renders" check passed on a badge beside the title | A digest change per zone image, and the new surface asserted INSIDE its own panel, not on a neighbouring element |
| 17 | **A session-gated 200 must not say `Cache-Control: public`.** `KEPT_HEADERS` passes the upstream's value through verbatim on responses that now require a session. No leak today (no `proxy_cache` on the Ingress) — wrong the moment one is added, which the author's own scaling note recommends | The header rewritten to `private` on gated routes, with a test |
| 18 | **The history log's `rows / bytes` column is `—` on every row** — noted while looking, not chased | Either populated from the lineage `row_count`/`size_bytes`, or the column removed; never a misleading `0` |
| 19 | **Condition 5 is not closed.** The user-state backend survives active attack (bob cannot read or delete alice's state — proven by inverting the key AND the owner check), but the verifier found an undisclosed data-loss path | The path named, fixed, and covered by a test that fails without the fix |
| 20 | **Workflows use `pipeline()`, not `parallel()`.** Three build agents sat finished for ~40 minutes because a barrier made the verify phase wait on the slowest one | No `parallel()` in a workflow script unless a stage genuinely needs every prior result at once, with the reason stated |

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
