# Where interactive state belongs — and why `setInterval` is the symptom, not the disease

Owner's question, asked three times and answered thinly each time until now: *"how come KV, cache, state
management or actors — any of it from Dapr — is not being used for this stuff? Lance is about OLAP and
storage, so how come."*

The short answer: **they are right.** The analytical plane is coherent; the *interactive* plane has no home
for its state, and the frontend's 15 polling timers are what that absence looks like from the outside.

## The causal chain, measured

| Layer | What we found | Evidence |
| ----- | ------------- | -------- |
| Frontend | 15 files poll with `setInterval`; `query.live` used in exactly **one** file; **zero** `EventSource`; no client query cache | `grep -rl setInterval` per zone; `admin.remote.ts` |
| Media-plane services | viewer / search / annotator: `publish:0 subscribe:0`, zero Dapr imports — sidecar and tracing only | vs medallion 4/7, catalog 2/2, lineage 0/3, compaction 1/2 |
| Dapr building blocks in use | pub/sub only | no state store, no actors, no workflow component in `chart/` |
| Store for operational state | none — so there is nowhere to put a task's state except Lance, which is the wrong shape | — |

Read it downwards and it is one fault, not four: **the UI polls because there is no event to subscribe to;
there is no event because those services publish nothing; they publish nothing because there is no
operational state model to publish *about*.**

## Why Lance must not hold this state

Lance is a columnar, immutable, **versioned** analytical format. Every commit is a new version with a
manifest and a transaction file — which is exactly why the git-like history in `#113` works so well.

That same property makes it wrong for interactive state. A per-task flip (`assigned → in progress →
submitted → reviewed`) is a small, frequent, single-entity write. In Lance each one would be a dataset
version: hundreds of manifests a minute, a version history that is noise rather than provenance, and
read-modify-write contention between annotators on a format with no row-level locking. It is not a
limitation of Lance; it is a category error to ask an OLAP format for OLTP semantics.

## The shape that fits, per building block

- **Lance** — published, immutable, versioned analytical data. Unchanged, and correct as it is.
- **Dapr state store (KV)** — annotation project/task state, assignments, review states, feed cursors, and
  caches of expensive shared reads (the lineage graph, the atlas projection). Small frequent reads and
  writes, no version per keystroke. The Dapr skill's own `statestore.yaml` is a `state.redis` component
  with `actorStateStore: "true"`.
- **Dapr actors** — one actor per task (or per project): single-threaded per entity, so two annotators
  cannot claim the same task, and a progress counter needs no lock. Actor **reminders** give claim leases
  for free — a task claimed and abandoned returns to the queue without a sweeper cron.
- **Dapr workflow** — the *sync* in "synced only when we choose to" (`#122`) is a saga: freeze the project,
  write the governed table, emit lineage, tag the version, mark published. Durable, retried, resumable.
  Note the skill's constraint: workflow uses the actor framework internally, so it needs that state store
  with `actorStateStore: "true"` — the state store is a prerequisite, not an alternative.
- **Dapr pub/sub** — the change signal. It already exists in the medallion plane and is absent in the media
  plane, which is why the annotator can save a label and nothing downstream reacts.
- **SvelteKit `query.live`** — the UI's subscription to that signal. The docs are explicit: live queries
  "do not have a `refresh()` method, **as they are self-updating**". Mutations use `command`/`form`, which
  invalidate dependent queries and return the refreshed data **in the same round trip** (single-flight), so
  after your own write you wait for nothing.

## What this replaces

Every `setInterval` in the frontend, and the idea that annotation state could live in the governed plane.
Neither is a small cleanup: the timers are a workaround for a missing subscription, and the state question
decides whether `#122` is buildable at all.

## Order of work

1. **State store component** in the chart (`actorStateStore: "true"` — it gates actors and workflow both).
2. **Annotation project/task state on it**, as `#122`'s own store. This is the piece that unblocks the
   labeling-platform task model.
3. **Publish on save** from the annotator, so there is an event to react to — and the active-learning
   trigger stops needing a poll.
4. **`query.live` per feed** in the zones, deleting each timer as its surface moves (`#102`).
5. **Workflow for the sync**, once there is state worth publishing.
6. **Cache the expensive shared reads** last — it is the only item here that is an optimisation rather than
   a correctness fix, and it needs an invalidation story the pub/sub signal now provides.

Steps 1–3 are backend and need no UI decision. Step 4 is mechanical once 3 exists. The owner's call is
needed only on the task schema in `#122` — what states a task has, who assigns, what "reviewed" means, and
what exactly a sync publishes.
