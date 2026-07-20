<script lang="ts">
	// `/tables/<id>` — the catalog table-detail view (#52): schema, stats, version + tag history, the
	// #50 maintenance policy (owner-gated set/delete), and the #51 access review. Data comes in one
	// round-trip through the /capi detail BFF aggregate; policy writes go through their own narrow
	// session-only routes. A dataset the catalog does not register (e.g. a storage-managed medallion
	// zone) renders the honest not-in-catalog state instead of a broken page.
	import { Database, RefreshCw, ShieldAlert, Trash2 } from "@lucide/svelte";
	import GrantsPanel from "./GrantsPanel.svelte";
	import ReadersPanel from "./ReadersPanel.svelte";
	import {
		createTableTag,
		deleteTablePolicy,
		fetchTableDetail,
		partErrored,
		type Policy,
		type PolicyRequest,
		type TableStats,
		type TableDetail,
		restoreTableVersion,
		setTablePolicy,
	} from "./catalog";

	let { table }: { table: string } = $props();

	let detail = $state<TableDetail | null>(null);
	let lastStatus = $state(0);
	let busy = $state(false);
	let policyError = $state<string | null>(null);
	let editingPolicy = $state(false);
	// number | null, matching what bind:value on a type="number" input actually delivers (Svelte 5
	// coerces to a number, or null for an empty field) — typing them as string crashed savePolicy's
	// guards the moment the user touched a field (audit 2026-07-16).
	let draft = $state<{
		retention_days: number | null;
		retain_versions: number | null;
		interval: number | null;
		enabled: boolean;
	}>({ retention_days: null, retain_versions: null, interval: null, enabled: true });

	// #64 version management — name (tag) a Lance version (writer-gated). Reset on table change below.
	let tagName = $state("");
	let tagVersion = $state<number | null>(null);
	let tagBusy = $state(false);
	let tagError = $state<string | null>(null);

	// #64 restore-to-version (owner-gated) — two-click confirm, since restore mutates the current table.
	let restoreConfirm = $state<number | null>(null);
	let restoreBusy = $state(false);
	let restoreError = $state<string | null>(null);

	// #64 blob preview — the credential-less read of a blob cell (GET /blobs?column=&row=), session-gated
	// by the catch-all BFF (reader-tier can_read_data). Only offered for binary/blob-typed columns.
	let blobCol = $state("");
	let blobRow = $state<number | null>(null);
	let blobSrc = $state<string | null>(null);
	let blobFailed = $state(false);

	const unauthorized = $derived(detail === null && lastStatus === 401);
	const notInCatalog = $derived(detail === null && lastStatus === 404);
	const denied = $derived(detail === null && lastStatus === 403);
	const offline = $derived(detail === null && ![0, 200, 401, 403, 404].includes(lastStatus));

	async function load(): Promise<void> {
		// Latest-wins: the user may navigate table A→B while A's request is in flight (the route reuses
		// this instance), so drop a response for a table we have already navigated away from.
		const requested = table;
		const res = await fetchTableDetail(requested);
		if (table !== requested) return;
		if (res.ok) {
			detail = res.data;
			lastStatus = 200;
		} else {
			lastStatus = res.status;
		}
	}

	$effect(() => {
		// Reset every piece of state on a table change — including the edit form, or an editor opened
		// on A would survive into B and Save would write A's draft to B (audit 2026-07-16).
		void table;
		detail = null;
		lastStatus = 0;
		editingPolicy = false;
		policyError = null;
		busy = false;
		tagName = "";
		tagVersion = null;
		tagError = null;
		restoreConfirm = null;
		restoreError = null;
		blobCol = "";
		blobRow = null;
		blobSrc = null;
		blobFailed = false;
		load();
	});

	function startPolicyEdit(): void {
		draft = {
			retention_days: policy?.retention_days ?? null,
			retain_versions: policy?.retain_versions ?? null,
			interval: policy?.compact_interval_hours ?? null,
			enabled: policy?.compact_enabled ?? true,
		};
		policyError = null;
		editingPolicy = true;
	}

	function policyFail(status: number, detailText: string): void {
		if (status === 401) policyError = "Sign in to edit the maintenance policy.";
		else if (status === 403) policyError = "Denied: policy changes need the owner rung (can_drop).";
		else policyError = detailText;
	}

	async function savePolicy(): Promise<void> {
		if (busy) return;
		busy = true;
		policyError = null;
		try {
			const body: PolicyRequest = { compact_enabled: draft.enabled };
			if (draft.retention_days != null) body.retention_days = draft.retention_days;
			if (draft.retain_versions != null) body.retain_versions = draft.retain_versions;
			if (draft.interval != null) body.compact_interval_hours = draft.interval;
			const res = await setTablePolicy(table, body);
			if (res.ok) {
				editingPolicy = false;
				await load();
			} else {
				policyFail(res.status, res.detail);
			}
		} finally {
			busy = false;
		}
	}

	async function removePolicy(): Promise<void> {
		if (busy) return;
		busy = true;
		policyError = null;
		try {
			const res = await deleteTablePolicy(table);
			if (res.ok) await load();
			else policyFail(res.status, res.detail);
		} finally {
			busy = false;
		}
	}

	async function runTag(): Promise<void> {
		const name = tagName.trim();
		if (tagBusy || !name || tagVersion == null) return;
		tagBusy = true;
		tagError = null;
		try {
			const res = await createTableTag(table, name, tagVersion);
			if (res.ok) {
				tagName = "";
				tagVersion = null;
				await load(); // pull the new tag into the tags row
			} else if (res.status === 401) {
				tagError = "Sign in to tag a version.";
			} else if (res.status === 403) {
				tagError = "Denied: tagging a version needs writer access (can_create_tag).";
			} else {
				tagError = res.detail;
			}
		} finally {
			tagBusy = false;
		}
	}

	async function runRestore(version: number | undefined): Promise<void> {
		if (restoreBusy || version == null) return;
		restoreBusy = true;
		restoreError = null;
		try {
			const res = await restoreTableVersion(table, version);
			if (res.ok) {
				restoreConfirm = null;
				await load(); // restore mints a fresh current version — refresh to show it
			} else if (res.status === 401) {
				restoreError = "Sign in to restore a version.";
			} else if (res.status === 403) {
				restoreError = "Denied: restoring a version needs the owner tier (can_restore).";
			} else {
				restoreError = res.detail;
			}
		} finally {
			restoreBusy = false;
		}
	}

	function previewBlob(): void {
		if (!blobCol || blobRow == null) return;
		blobFailed = false;
		// The catch-all BFF forwards the query + the session bearer + the binary body → an <img> src works.
		blobSrc = `/capi/v1/table/${encodeURIComponent(table)}/blobs?column=${encodeURIComponent(blobCol)}&row=${blobRow}`;
	}

	// Split each part into "resolved value" vs "upstream failed" so the markup can render an honest
	// "unavailable" instead of an affirmative empty state (which for policy would invite an overwrite).
	const stats = $derived(
		partErrored(detail?.stats) ? null : ((detail?.stats ?? null) as TableStats | null),
	);
	const policy = $derived(
		partErrored(detail?.policy) ? null : ((detail?.policy ?? null) as Policy | null),
	);
	const policyUnavailable = $derived(partErrored(detail?.policy));
	const schemaFields = $derived(
		(detail?.describe.schema?.fields ?? []) as {
			name?: string;
			type?: unknown;
			nullable?: boolean;
		}[],
	);
	// Columns whose type is binary/blob — the ones the blob preview can read a cell from.
	const blobColumns = $derived(
		schemaFields
			.filter((f) => /binary|blob/i.test(typeName(f.type)))
			.map((f) => f.name)
			.filter((n): n is string => !!n),
	);
	const versions = $derived(
		partErrored(detail?.versions)
			? []
			: ((detail?.versions?.versions ?? []) as {
					version?: number;
					timestamp_millis?: number | null;
					manifest_size?: number | null;
					e_tag?: string | null;
				}[]),
	);
	const tags = $derived(
		partErrored(detail?.tags)
			? []
			: Object.entries((detail?.tags?.tags ?? {}) as Record<string, { version?: number }>),
	);
	// Lance branches: a name → BranchContents map (createAt in seconds, manifestSize in bytes).
	const branches = $derived(
		partErrored(detail?.branches)
			? []
			: Object.entries(
					(detail?.branches?.branches ?? {}) as Record<
						string,
						{ createAt?: number; manifestSize?: number | null }
					>,
				),
	);
	// Indexes on the table (#64) — scalar/vector, each over one or more columns.
	const indexes = $derived(
		partErrored(detail?.indexes)
			? []
			: ((detail?.indexes?.indexes ?? []) as {
					index_name?: string;
					columns?: string[];
					index_type?: string | null;
				}[]),
	);

	function typeName(t: unknown): string {
		if (t && typeof t === "object" && "type" in t) return String((t as { type: unknown }).type);
		return String(t ?? "—");
	}

	function fmtBytes(n: number | null | undefined): string {
		if (n == null) return "—";
		const units = ["B", "KiB", "MiB", "GiB", "TiB"];
		let v = n;
		let u = 0;
		while (v >= 1024 && u < units.length - 1) {
			v /= 1024;
			u += 1;
		}
		return `${v.toFixed(v >= 10 || u === 0 ? 0 : 1)} ${units[u]}`;
	}

	// version manifest timestamps arrive in ms; branch createAt in seconds — normalise to one UTC string.
	function fmtEpoch(value: number | null | undefined, unit: "ms" | "s"): string {
		if (value == null) return "—";
		const ms = unit === "s" ? value * 1000 : value;
		return `${new Date(ms).toISOString().replace("T", " ").slice(0, 16)}Z`;
	}
</script>

<div class="page">
	<header>
		<Database size={16} />
		<h1 class="mono">{table}</h1>
		{#if detail?.describe.version != null}
			<span class="sub mono">v{detail.describe.version}</span>
		{/if}
	</header>

	{#if unauthorized}
		<div class="empty">
			<ShieldAlert size={16} />
			<p>This stack is governed — <a href="/auth/login">sign in</a> to view table details.</p>
		</div>
	{:else if notInCatalog}
		<div class="empty">
			<p>
				Not a catalog-registered table — storage-managed datasets (medallion zones) have no catalog
				detail. Its lineage is on the <a href="/">explorer</a>.
			</p>
		</div>
	{:else if denied}
		<div class="empty">
			<ShieldAlert size={16} />
			<p>
				You don't have read access to this table's catalog metadata — its lineage is on the <a
					href="/">explorer</a
				>.
			</p>
		</div>
	{:else if offline}
		<div class="empty">
			<RefreshCw size={16} />
			<p>Catalog unreachable (HTTP {lastStatus}).</p>
		</div>
	{:else if detail === null}
		<div class="empty"><p>Loading…</p></div>
	{:else}
		<section>
			<h2>Stats</h2>
			{#if partErrored(detail.stats)}
				<p class="mut">Stats unavailable right now.</p>
			{:else}
				<div class="stats mono">
					<span>{stats?.num_rows ?? "—"} rows</span>
					<span>{fmtBytes(stats?.total_bytes)}</span>
					<span>{stats?.num_indices ?? 0} indices</span>
					{#if detail.describe.location}<span class="loc">{detail.describe.location}</span>{/if}
				</div>
			{/if}
		</section>

		<section>
			<h2>Schema</h2>
			{#if schemaFields.length === 0}
				<p class="mut">Schema unavailable for this table.</p>
			{:else}
				<table>
					<thead><tr><th>field</th><th>type</th><th>nullable</th></tr></thead>
					<tbody>
						{#each schemaFields as f (f.name)}
							<tr>
								<td class="mono">{f.name}</td>
								<td class="mono">{typeName(f.type)}</td>
								<td class="mono">{f.nullable ? "yes" : "no"}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<section>
			<h2>Blob preview</h2>
			{#if blobColumns.length === 0}
				<p class="mut">No blob columns on this table.</p>
			{:else}
				<div class="refs tagform">
					<select class="mono" bind:value={blobCol}>
						<option value="" disabled>column…</option>
						{#each blobColumns as c (c)}<option value={c}>{c}</option>{/each}
					</select>
					<input class="mono" type="number" min="0" placeholder="row" bind:value={blobRow} />
					<button class="btn" disabled={!blobCol || blobRow == null} onclick={previewBlob}
						>Preview</button
					>
				</div>
				{#if blobSrc}
					{#if blobFailed}
						<p class="mut">
							Not an inline-previewable image — <a href={blobSrc}>open the blob</a>.
						</p>
					{:else}
						<img
							class="blob"
							src={blobSrc}
							alt="blob preview"
							onerror={() => (blobFailed = true)}
						/>
					{/if}
				{/if}
			{/if}
		</section>

		<section>
			<h2>Indexes</h2>
			{#if indexes.length === 0}
				<p class="mut">No indexes on this table.</p>
			{:else}
				<div class="refs">
					{#each indexes as ix (ix.index_name)}
						<span class="chip mono"
							>{ix.index_name}<span class="mut">
								· {(ix.columns ?? []).join(", ")}{ix.index_type ? ` · ${ix.index_type}` : ""}</span
							></span
						>
					{/each}
				</div>
			{/if}
		</section>

		<section>
			<h2>Versions, branches & tags</h2>
			{#if versions.length === 0}
				<p class="mut">No version history available.</p>
			{:else}
				<p class="mut">
					{versions.length} version{versions.length === 1 ? "" : "s"} — most recent first, one Lance manifest
					per commit:
				</p>
				<table>
					<thead><tr><th>version</th><th>committed</th><th>manifest</th><th></th></tr></thead>
					<tbody>
						{#each versions.slice().reverse().slice(0, 10) as v (v.version)}
							<tr>
								<td class="mono">v{v.version}</td>
								<td class="mono">{fmtEpoch(v.timestamp_millis, "ms")}</td>
								<td class="mono">{fmtBytes(v.manifest_size)}</td>
								<td class="act">
									{#if restoreConfirm === v.version}
										<button
											class="btn tiny danger"
											disabled={restoreBusy}
											onclick={() => runRestore(v.version)}
										>
											{restoreBusy ? "…" : "confirm restore"}
										</button>
										<button class="btn tiny ghost" onclick={() => (restoreConfirm = null)}>
											cancel
										</button>
									{:else}
										<button
											class="btn tiny ghost"
											onclick={() => {
												restoreConfirm = v.version ?? null;
												restoreError = null;
											}}
										>
											restore
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				{#if versions.length > 10}<p class="mut">…and {versions.length - 10} older.</p>{/if}
				{#if restoreError}<p class="error">{restoreError}</p>{/if}
			{/if}

			<div class="refs br">
				<span class="mut">branches:</span>
				{#if branches.length === 0}
					<span class="chip mono">main</span>
					<span class="mut">(no additional branches)</span>
				{:else}
					{#each branches as [name, b] (name)}
						<span class="chip branch mono"
							>{name}<span class="mut"> · {fmtBytes(b.manifestSize)}</span></span
						>
					{/each}
				{/if}
			</div>

			<div class="refs">
				{#if tags.length === 0}
					<span class="mut">No tags — a promotion pins its version with one (e.g. blessed).</span>
				{:else}
					{#each tags as [name, t] (name)}
						<span class="chip tag mono">{name} → v{t.version}</span>
					{/each}
				{/if}
			</div>

			{#if versions.length > 0}
				<div class="refs tagform">
					<input class="mono" placeholder="tag name (e.g. blessed)" bind:value={tagName} />
					<select class="mono" bind:value={tagVersion}>
						<option value={null} disabled>version…</option>
						{#each versions as v (v.version)}<option value={v.version}>v{v.version}</option>{/each}
					</select>
					<button
						class="btn"
						disabled={tagBusy || !tagName.trim() || tagVersion == null}
						onclick={runTag}
					>
						{tagBusy ? "…" : "Tag version"}
					</button>
					{#if tagError}<span class="error">{tagError}</span>{/if}
				</div>
			{/if}
		</section>

		<section>
			<h2>Maintenance policy</h2>
			{#if editingPolicy}
				<div class="policy-edit">
					<label
						>retention days <input
							class="mono"
							type="number"
							min="1"
							bind:value={draft.retention_days}
							placeholder="global default"
						/></label
					>
					<label
						>retain versions <input
							class="mono"
							type="number"
							min="1"
							bind:value={draft.retain_versions}
							placeholder="—"
						/></label
					>
					<label
						>compact every (h) <input
							class="mono"
							type="number"
							min="1"
							bind:value={draft.interval}
							placeholder="every sweep"
						/></label
					>
					<label class="check"
						><input type="checkbox" bind:checked={draft.enabled} /> maintenance enabled</label
					>
					<div class="row">
						<button class="btn" disabled={busy} onclick={savePolicy}>Save policy</button>
						<button class="btn ghost" onclick={() => (editingPolicy = false)}>Cancel</button>
					</div>
				</div>
			{:else if policyUnavailable}
				<p class="mut">
					Policy unavailable right now — not shown to avoid an overwriting edit against a stale
					read.
				</p>
			{:else if policy}
				<div class="refs">
					{#if policy.retention_days}<span class="chip mono"
							>retention {policy.retention_days}d</span
						>{/if}
					{#if policy.retain_versions}<span class="chip mono"
							>keep last {policy.retain_versions}</span
						>{/if}
					{#if policy.compact_interval_hours}<span class="chip mono"
							>every {policy.compact_interval_hours}h</span
						>{/if}
					{#if !policy.compact_enabled}<span class="chip off mono">maintenance off</span>{/if}
					<button class="btn ghost" onclick={startPolicyEdit}>Edit</button>
					<button class="btn ghost danger" disabled={busy} onclick={removePolicy}>
						<Trash2 size={12} /> Remove
					</button>
				</div>
				<p class="mut">
					Enforced by the compaction sweep; tag-pinned versions (e.g. blessed) are never cleaned up.
				</p>
			{:else}
				<p class="mut">
					No policy — the sweep applies the global defaults.
					<button class="btn ghost" onclick={startPolicyEdit}>Set policy</button>
				</p>
			{/if}
			{#if policyError}<p class="error">{policyError}</p>{/if}
		</section>

		<section>
			<h2>Access</h2>
			<GrantsPanel dataset={table} />
			<ReadersPanel dataset={table} />
		</section>
	{/if}
</div>

<style>
	.page {
		max-width: 860px;
		margin: 0 auto;
		padding: 56px 20px 40px;
	}
	header {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 18px;
	}
	h1 {
		font-size: 18px;
		margin: 0;
	}
	h2 {
		font-size: 13px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--faint);
		margin: 0 0 8px;
	}
	section {
		margin-bottom: 22px;
	}
	.sub {
		color: var(--faint);
		font-size: 12px;
	}
	.stats {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		font-size: 12px;
		color: var(--mut);
	}
	.loc {
		color: var(--faint);
	}
	table {
		border-collapse: collapse;
		font-size: 12px;
		width: 100%;
	}
	th {
		text-align: left;
		color: var(--faint);
		font-weight: 500;
		padding: 3px 14px 3px 0;
		border-bottom: 1px solid var(--line);
	}
	td {
		padding: 3px 14px 3px 0;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
	}
	.refs {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-bottom: 6px;
		font-size: 12px;
	}
	.chip {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		padding: 0 7px;
	}
	.chip.tag {
		border-color: color-mix(in srgb, var(--ok) 45%, var(--line));
	}
	.chip.off {
		border-color: color-mix(in srgb, var(--amber) 55%, var(--line));
	}
	.chip.branch {
		border-color: color-mix(in srgb, var(--faint) 60%, var(--line));
	}
	.refs.br {
		margin-top: 10px;
	}
	.mut {
		color: var(--faint);
		font-size: 12px;
	}
	.error {
		color: var(--fail);
		font-size: 12px;
	}
	.empty {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--mut);
		padding: 32px 0;
	}
	.policy-edit {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: end;
		font-size: 12px;
		color: var(--mut);
	}
	.policy-edit label {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.policy-edit label.check {
		flex-direction: row;
		align-items: center;
		gap: 6px;
	}
	.policy-edit input[type="number"] {
		width: 110px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		padding: 4px 8px;
		font-size: 12px;
	}
	.tagform input,
	.tagform select {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 3px 8px;
	}
	.tagform input {
		width: 150px;
	}
	.btn {
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 3px 10px;
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.btn.tiny {
		font-size: 11px;
		padding: 1px 7px;
	}
	.act {
		white-space: nowrap;
		text-align: right;
	}
	.blob {
		display: block;
		max-width: 100%;
		max-height: 320px;
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		margin-top: 10px;
	}
	.btn.ghost {
		background: none;
		color: var(--mut);
	}
	.btn.danger {
		color: var(--fail);
	}
	.row {
		display: flex;
		gap: 8px;
	}
</style>
