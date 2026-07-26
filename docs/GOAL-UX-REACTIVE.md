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
| 3 | **Notifications exist.** A run that starts, finishes or fails is surfaced without the user hunting for it, in every zone, from `/runs` — no new backend | Drive a real cascade run as alice; screenshot the surface showing START then COMPLETE/FAIL with its error text |
| 4 | **The timers are gone.** `setInterval` replaced by `query.live` on the lineage cursor | `grep -rl setInterval` per zone, with a stated reason for any survivor |
| 5 | **User work persists.** The workflow graph and saved views leave `localStorage` for the state store, per subject | Write in one browser context, read it in a fresh one — proven, not asserted |
| 6 | **The expensive read is cached server-side.** Redis, authorize-every-request, keyed on `(resource, version)`, single-flight | A second user's first atlas load serves from cache; a user without access still gets 403 |
| 7 | **Green and pushed.** Every gate, cold | Python 1173+, whole-repo `ty`, `ruff services tests`, all four zone suites, `turbo --force`, prod-render, CI read to completion |

## Rules I am holding myself to

- **Read the code before designing.** Three corrections in one session came from not doing this: the
  notification backend already existed, the secret store was already the estate's rule, and `lance-secrets`
  scoping was already documented as a failure class.
- Evidence over assertion; a test that cannot fail is not a test.
- Backward compatibility does not matter — change it to the right thing and update every caller.
- Take screenshots for frontend work and **look** at them.

## Status

Tracked live in `docs/GOAL-VERIFY-PULL.md`'s ledger. Conditions close here as they are proven.
