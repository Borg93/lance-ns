# Lance Namespace Catalog — Interactive System Diagram

Companion to **[`system-diagram.html`](./system-diagram.html)** — a single-file, click-through
diagram of the catalog. Open it in a browser:

```bash
xdg-open docs/system-diagram.html      # Linux
# or just drag the file into any browser — no server, no build
```

This markdown is self-sufficient: you can read the whole system here without opening the HTML,
and vice-versa. For the prose architecture see [`ARCHITECTURE.md`](./ARCHITECTURE.md); for the
gap register + Lakekeeper diff see [`SYSTEM-SKETCH.md`](./SYSTEM-SKETCH.md).

> **What the HTML adds:** pick a flow tab, press **Space** to play, and watch each request hop
> light up one wire + one node with its real payload on the side panel. Toggle the **data-plane
> mode** to see how the *same* operation changes shape on HCP vs S3. Click any node to jump to
> where it first appears; drag to re-layout; **T** = light/dark, **F** = fullscreen.

---

## The one idea

Three planes, three governance axes, **one identity**. Every table is `table:<id>` — and that
*same* string is the OpenFGA object (who may), the Lance dataset (what/when), and the lineage
graph node (how/who). The diagram is built around that single identity threading through all three.

| Plane | Question | Component in the diagram |
|---|---|---|
| **Control** | who may, where is it | **Catalog** (FastAPI/pylance) + **OIDC** + **OpenFGA** |
| **Data** | the bytes | **Object store** (HCP / MinIO·S3), reached by **Mode B** or **Vending** |
| **Provenance** | how/who did it change | **Lineage svc** (OpenLineage) → **AGE graph** *(job-emitted; partial — see note)* |

> ⚠️ **Provenance is partial today (audit `w8u4rc2tg`).** The **catalog emits no lineage** (`grep app/`
> = no matches) — the AGE graph is populated only by the `lineage/seed.py` demo emitter. Table
> creation/DDL is **not** captured, and the run `author` is **self-asserted by the producer**, not
> verified against a token. Treat the provenance plane as *designed, not yet authoritative*.

---

## Modes — the data-plane shape (toggle, top-left)

Modes are **not** alternate flows; they're the deployment shape of the *data plane*. The same
flow runs in both — only the credential/byte-path changes.

| | **HCP · Mode B** *(default, prod reality)* | **S3 · Vending** *(dev / S3-family target)* |
|---|---|---|
| Object store | Hitachi HCP — S3 API, **no STS** | MinIO / Ceph / S3 — **STS** |
| Credential | **none leaves the catalog** | short-TTL, table-scoped **STS token** |
| Byte path | **server-mediated** (catalog reads on the client's behalf) | client reads storage **directly** with the vended token |
| OpenBao | not consulted per-request | catalog reads **its own** base key to mint STS (planned) |

HCP is today's *reality*, not the long-term *target* — so the design is **vending-first** with a
pluggable `CredentialVendor` (`app/core/vending.py`: `ModeBVendor` / `StaticPrefixVendor` /
`StsVendor`), and Mode B is the most-secure option achievable where STS doesn't exist.

> ⚠️ **HCP credential reality (audit `w8u4rc2tg`).** HCP has **no STS** and **no per-bucket / per-prefix
> keys**. Its only key material is the *user's own* identity key — `access_key=base64(username)`,
> `secret_key=md5(password)` (`ra-hcp .../auth_utils.py:37-38`) — long-lived, unrotatable without a
> password change, and **tenant-wide**. So on HCP "static" would mean handing out a full-privilege
> identity key, *not* a scoped per-bucket key. **HCP is Mode B only**; the "static per-bucket keys
> from OpenBao" story applies to **S3 / MinIO**, never HCP.

> 🔑 **Who holds secrets (least-privilege).** Only the **catalog** and **lineage svc** consume OpenBao.
> Compute jobs (**lance-ray**) **never** read OpenBao — they get short-TTL scoped creds *from the
> catalog* and authenticate with **workload identity** (KubeRay SA / OIDC token), not a vault key.
> That is why only the catalog connects to OpenBao in the diagram — by design, not omission.

---

## Nodes

| Node | Role (color) | What it is |
|---|---|---|
| **Client** | user (mint) | LanceDB SDK / `lance-ray` / app — speaks the REST + Arrow API |
| **lance-ray job** | compute (magenta) | medallion promotion + compaction on the KubeRay cluster (a catalog *client*, not an endpoint) |
| **OIDC IdP** | embed (amber) | Dex — issues JWTs; catalog verifies against JWKS (fail-closed) |
| **OpenBao** | seed (orange) | secrets · KV v2 — **catalog + lineage only**; jobs use workload identity (planned) |
| **Catalog** | orch (sky) | FastAPI over native `pylance` `DirectoryNamespace`; the control plane |
| **OpenFGA** | vector (violet) | authz (Postgres) — `can_*` actions, concentric owner⊇writer⊇reader, parent cascade |
| **Object store** | vector (violet) | the data plane — HCP (prod) or MinIO/S3 (dev), label/tech swap by mode |
| **Lineage svc** | orch (sky) | FastAPI; ingests OpenLineage, serves upstream/downstream/producers/graph |
| **AGE graph** | vector (violet) | Apache AGE (Postgres) — the provenance DAG, queried with openCypher |

---

## Flows (the tabs)

### 1. Create table — `POST /v1/table/{id}/create`
1. **Client → Catalog** — Arrow-IPC create with a Bearer JWT.
2. **Catalog → OIDC** — verify JWT against JWKS (cached); bad/absent token → 401.
3. **Catalog → OpenFGA** — `check can_create_table` on the **parent** namespace.
4. **Catalog → Object store** — create the Lance dataset location + record the table (version 1).
5. **Catalog → OpenFGA** — `grant_on_create`: seed `owner` grant + `parent` edge (inherits cascade).
6. **Catalog → Client** — `201`; caller is the table's **owner** (⇒ writer ⇒ reader).

### 2. Read / query — `GET describe_table` (+ read)
1. **Client → Catalog** — describe (optionally `?vend_credentials=true`).
2. **Catalog → OIDC** — verify token.
3. **Catalog → OpenFGA** — `check can_read_data` (reader rung; cascades).
4. **Catalog → OpenBao** *(planned, S3 only)* — read the catalog's **own base key** to mint an STS token; **Mode B fetches nothing** (compute jobs never read OpenBao — see the Secrets note above).
5. **Catalog → Object store** — return location; **S3** also returns a short-TTL STS token, **HCP** returns location only.
6. **Client → Object store** — **S3:** read directly with the vended token. **Mode B:** the read instead goes through the catalog's Arrow-IPC query endpoint (no creds on the client).

### 3. Promote (medallion) — `lance-ray` bronze → silver → gold  *(target flow — the lance-ray jobs and lineage emission are not built yet; today only the `lineage/seed.py` demo emitter populates the graph)*
1. **Job → Catalog** — describe bronze (the job is a catalog client; it authenticates with **workload identity**, never OpenBao).
2. **Catalog → OpenFGA** — `check can_read_data` for `role:data_engineer#assignee` (role-as-subject).
3. **Job → Object store** — read only the **new bronze versions** — the version range *is* the change feed.
4. **Job → Catalog** — `merge_insert` silver with an `Idempotency-Key` (authorizes `can_write_data`; retry-safe).
5. **Job → Object store** — write the new silver dataset version (immutable; old versions stay for time-travel).
6. **Job → Lineage** — emit an OpenLineage run event: inputs=[bronze], outputs=[silver], `author` = **self-asserted producer facet, NOT token-verified** (server-side verification + ingest authz are planned, P0).
7. **Lineage → AGE** — `MERGE` Run/Job/Dataset + `WROTE`/`DERIVED_FROM` edges; dataset name = `table:<id>`.

### 4. Lineage query — `GET /datasets/{id}/upstream`
1. **Client → Lineage** — ask "where did gold come from?"
2. **Lineage → OIDC** *(planned, P0)* — verify JWT. **Today reads are unauthenticated — a P0 gap.**
3. **Lineage → OpenFGA** *(planned, P0)* — `check can_get_metadata` (same right as describe-table); reuses the shared store, read-only.
4. **Lineage → AGE** — openCypher `DERIVED_FROM*1..` traversal; the dataset name is an **agtype bind param**, never interpolated (injection-safe).
5. **Lineage → Client** — `200` with the transitive upstream set.

> **The headline gaps the diagram makes visible (audit `w8u4rc2tg`):**
> 1. *Lineage query* steps 2–3 are dashed "planned" — the read endpoints **leak the entire data
>    estate** (no authz). **P0**.
> 2. The lineage **ingest** side is *also* unauthenticated, and the `author` is **self-asserted** —
>    so recorded provenance/authorship is **forgeable** (latent: the lineage svc isn't deployed yet). **P0-on-deploy**.
> 3. The **catalog emits no lineage at all** — so "who created the table" is *not* recorded as an
>    audit fact (only an OpenFGA `owner` tuple, which is an *access* fact). **P0**.
>
> All three are tracked in [`todo.md`](../todo.md) (Next, P0).

---

## Workshop scenarios

- **"Show me security end-to-end"** — run *Create table*; pause on steps 2→3→5 (verify → authorize → seed-ownership). The cascade is why one create grants exactly the right future access.
- **"Why is HCP different?"** — open *Read / query*, step through once in **HCP · Mode B**, then flip to **S3 · Vending** and step again. Same flow, two credential stories.
- **"Where does lineage come from?"** — run *Promote*; the last two steps (emit → MERGE) show provenance is a **byproduct of the job** (the *target* design). Caveat: not built yet, and the author is producer-claimed until ingest authz lands.
- **"What's still open?"** — *Lineage query*, steps 2–3: the dashed planned authz gate (P0).
