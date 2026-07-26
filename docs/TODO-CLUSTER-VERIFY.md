# TODO — what still needs a real environment

Everything in this file was **written and unit/e2e-tested in a sandbox with no docker, kind or helm**.
The frontend gates all pass (`turbo run check check:tsgo test lint fmt:check build`, 47/47) and the
Playwright suite passes from a cold cache (205 tests, 4 zones) — but none of that touches an image, a
chart render, or a cluster. This is the list of things that are therefore **unproven**, in the order
they will break.

Each item says what to run, what it should do, and **why it is on the list** — i.e. what specifically
changed under it.

---

## 1. Build the zone images — the highest-risk item

```bash
make frontend-images          # docker build × 4, lance-<zone>:dev
```

**Why:** `.docker/frontend.dockerfile` has not successfully built since before the zone merge, and two
separate bugs were fixed blind:

- `eslint-rules` was a frontend workspace member the dockerfile never `COPY`d, so
  `bun install --frozen-lockfile` inside the builder would fail with **"Workspace not found"** for
  every zone. It was fixed as a side effect of deleting ESLint.
- `Makefile: ZONES` still listed the seven pre-merge zones, so the loop died on
  `--build-arg APP=data` and never reached `lakehouse`.

Both now have gates in `@repo/zone-contract` (every workspace glob has a COPY line; `ZONES` equals the
zone directories), but **a passing gate is not a passing build.**

- [x] All four images build: `home`, `lakehouse`, `media`, `annotator` — verified 2026-07-26; rebuilt again
      the same day after the navbar/link fixes so the running images match the shipped source.
- [x] `docker run --rm lance-home:dev` answers on :3000 — `home` 200 at `/`, `lakehouse` 307 → `/lakehouse/data`
      → 200. NOTE the gate weakness found while doing this: the dockerfile HEALTHCHECK probes `/` and accepts
      `<500`, so a BASED zone reports healthy while 404ing its own probe. Defensible (it proves the SSR server
      is alive) but it never exercises the app.
- [x] All four run as uid **10001**, non-root — checked per image, not just `home`.
- [x] Sizes: home 1.32 / lakehouse 1.34 / media 1.35 / annotator 1.42 GB. The annotator is only ~8% above
      the others, so the wasm is not the blowup this line feared. The surprise was elsewhere and is now
      measured: of the annotator's 4179 KB gzipped CLIENT bundle, 3809 KB is the OpenCV chunk and it loads
      only on first use of the magnetic tool — see the budget-gate defect in docs/GOAL-VERIFY-PULL.md.

## 2. Render the chart

```bash
helm lint ./chart
helm template lance ./chart > /tmp/render.yaml
make charts                   # the chart CI gate via Dagger (helm lint + render invariants)
```

**Why:** the chart changed in three ways this session and none has been rendered.

- [x] Exactly four `web-<zone>` Deployments, no stale ones. Related defect found and fixed while checking:
      `chart/templates/network-policy.yaml:253` still admitted `web-admin` to the NATS monitor, so the rule
      matched NO pod and the prod ops view could not reach varz/jsz — default-deny fails closed and silently
      (`f4c545d`).
- [ ] **Per-zone image tags** work: set `tag:` on one entry of `frontend.apps` and confirm only that
      Deployment moves. This is the whole point of the zone split — if one shared tag ships every zone,
      independent deploy buys nothing.
      **Verified**: pinning only `media` to `probe-xyz` left the other three on `dev`.
- [ ] **Per-zone media env is scoped**: `media` gets `VIEWER_API` + `ANNOTATOR_API` + `SEARCH_API`;
      `annotator` gets `VIEWER_API` + `ANNOTATOR_API` and **no `SEARCH_API`**. `lakehouse`/`home` get
      neither. (`chart/templates/frontends.yaml`)
      **Verified on the LIVE pod env, not the template**: media = VIEWER+ANNOTATOR+SEARCH; annotator =
      VIEWER+ANNOTATOR with no `SEARCH_API`; home/lakehouse neither.
- [x] Ingress: `/lakehouse`, `/media`, `/annotator` Prefix + `/` catch-all last; base paths agree with
      each zone's `svelte.config.js`.

## 3. Deploy and drive the composed estate

```bash
make up                       # kind-up + deps + images + load + deploy
# or, against a live cluster: make frontend-images frontend-load deploy
```

- [ ] Every zone pod reaches Ready (the `bun ./build/index.js` runtime contract)
- [ ] **Cross-zone navigation** through the real Ingress: `/` → `/lakehouse/data` → `/media` →
      `/annotator`. Each cross-zone hop is a full document load; each **must not 404**. The
      `data-sveltekit-reload` gate is unit-enforced now (`@repo/zone-contract`, on Svelte's own
      compiler) but only a browser proves the Ingress prefix rules agree with the base paths.
- [ ] **The sealed session cookie carries across zones** on the one origin — sign in on `home`, land on
      `/lakehouse/admin` still signed in. `scripts/verify_cross_zone_oidc.sh`
- [ ] Assets load per zone (each zone serves its chunks from its own `/<zone>` prefix — a base-path
      drift shows up as 404ing chunks, not as a broken page)

## 4. The security work — this is the part that most needs a real backend

The estate-admin door moved to the **server** this session
(`components/frontends/lakehouse/src/routes/admin/+layout.server.ts`). The e2e proves the logic against
a **mock** catalog. What it cannot prove is that the real catalog's `/v1/me` answers the shape the door
reads. See `docs/AUTHZ.md` for the full matrix.

Deploy **auth ON + FGA ON**, then:

- [ ] An `estate_admin` identity reaches `/lakehouse/admin/*` and every panel renders
- [ ] A **non-admin** gets `403` from the server — check the **response status**, not just the page
      body, and confirm no admin HTML/JS was shipped (view-source / network tab)
- [ ] The non-admin's navbar shows **no** Governance or Operations column in the Lakehouse panel
- [ ] Signed-out page load redirects to `/auth/login?redirect=…`; a signed-out **API** call still gets
      `401` JSON (not an HTML redirect) — `isGatedPageRequest` deliberately splits these
- [ ] **Writes are refused without a session**: `POST /lakehouse/capi/v1/table/<id>/drop` with no
      cookie → `401` from the BFF, request never leaves it
- [ ] `POST /lakehouse/capi/v1/access/check` with no cookie → `401` (**changed this session** — it used
      to forward anonymously and rely on the catalog to refuse)
- [ ] **The service-credential read path**: with no user session, a lineage `GET` still works via
      `LINEAGE_SERVICE_TOKEN`. Confirm `frontend.serviceIdentity` (`service-web`) is READER on the
      warehouse and allowlisted in `LINEAGE_SERVICE_SUBJECTS` — this is the one place in the estate
      where an anonymous read is served, so its FGA grant is the entire blast radius.
- [ ] A **write** never gets the service credential (grep the lineage access log for
      `x-lance-service-identity` on a non-GET — there should be none)

## 5. The media/annotator split, against real services

- [ ] `media` reaches viewer + search + annotator; `annotator` reaches viewer + annotator and **never**
      search (watch the pods' egress, not just the env)
- [ ] `/media/graph` actually renders. In the sandbox it showed an empty flow root — that was traced to
      the absent backend (`{#if gw > 0 && gh > 0 && graphNodes.length > 0}`), **not** to a code change,
      but it has never been seen working since the merge.
- [ ] The annotator's runner chip tells the truth (`MEDIA_ASSIST_URL` / `runners.enabled`) — it lied
      once already (runner deployed, chip still said "mocked")

## 6. Bundle budgets on real hardware

```bash
bun run build && bunx turbo run test --filter=@repo/zone-contract
```

- [x] The budgets hold, and the doubt in this line turned out to be well placed — though the defect was
      worse than "did it run". The gate was measuring the WRONG THING: it gzipped every emitted file and
      called the total "what the browser pays to enter a zone", but 3809 of the annotator's 4179 KB is an
      OpenCV chunk behind a dynamic `import()`. So the annotator read 87% of budget while its real entry
      cost was 324 KB, and a change that DOUBLED the entry graph would have passed unnoticed. It also made
      the estate unreadable: on entry cost media is the heaviest zone (927 KB) and the annotator the
      second-lightest — the opposite of what `budget.json`'s own note and the test named "the annotator
      split still pays for itself" both asserted. Now measured in two halves from Vite's manifest
      (`imports` vs `dynamicImports`), both ceilinged, with the OpenCV-stays-lazy invariant as a named
      test. Fixed in `56a6aad`; each new gate was broken deliberately and watched to fail.
      Measured static/deferred gz KB: home 157/1, lakehouse 490/46, media 927/46, annotator 324/3854.
- [x] "Confirm it actually ran rather than trusting a green" — the skip-when-unbuilt hole is still there by
      design (`turbo run test` does not depend on `build`), but it is no longer silent in practice: the
      run that matters is CI's, where `@repo/zone-contract#test` explicitly dependsOn all four zone builds
      in `frontend/turbo.json`, so a build always exists there.

---

## Toolchain follow-ups (no cluster needed, just a later release)

- [ ] **Retire `svelte-check` + `typescript@6` → TypeScript 7 everywhere.** Blocked on
      `@rsvelte/svelte-check`: at `0.5.1` it emits 23 phantom `Cannot find module '$env/dynamic/private'`
      on `media` and `annotator`, and ignores `compilerOptions.experimental.async`. Both fail-*closed*
      (noise, not silence) — the previous fail-open blocker is gone. Re-test on each release:
      `bunx rsvelte-check --tsgo --tsconfig ./tsconfig.json` per zone. See `frontend/TOOLING.md`.
- [ ] **Re-check the nine disabled oxlint rules** on `@rsvelte/oxlint-plugin` releases. Each is off with
      its reason in `.oxlintrc.json`; the two big ones (`no-unused-class-name`,
      `consistent-selector-style`, 582 hits) assume components own their CSS and may never fit a
      Tailwind codebase.
- [ ] `oxfmt` is still a dependency because `rsvelte-fmt` delegates non-`.svelte` files to it. If
      rsvelte-fmt ever formats everything in-process, the dep goes.

## Open decisions — yours, not mine

- [ ] **Should `media` get the Pixi viewer?** Right now only `annotator` imports `@repo/engine`; media
      does read-only playback (`<video>`/`<audio>` + its own atlas/treemap canvases). media had a stale
      dependency on `@repo/engine` importing nothing — removed. Giving media the real read+write viewer
      is a genuine change, not a config flip, and it would move media's bundle toward annotator's, which
      would invalidate the argument for them being separate zones (`budget.test.ts` asserts
      `annotator > media × 2`).
- [ ] **The data plane's destructive controls render for everyone.** Drop / deregister / grant / revoke
      show for any signed-in user and the catalog's `can_drop` gate refuses the call. That is
      authorization-correct and disclosure-loose. Hiding them needs a per-object capability in the
      frozen `/v1/me` contract — a **backend** change. Decide whether you want it.
- [ ] **`rask` → `compute` rename.** Packages are already `@repo/*` precisely so this costs nothing on
      the frontend side; the zone names and docs still say `rask` in places.
