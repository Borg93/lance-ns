<script lang="ts">
	// `/tables/<id>` — the catalog table-detail view (#52): schema, stats, version + tag history, the
	// #50 maintenance policy (owner-gated set/delete), and the #51 access review. Data comes in one
	// round-trip through the /capi detail BFF aggregate; policy writes go through their own narrow
	// session-only routes. A dataset the catalog does not register (e.g. a storage-managed medallion
	// zone) renders the honest not-in-catalog state instead of a broken page.
	import { Select } from "@lance/ui";
	import { Database, RefreshCw, ShieldAlert, Trash2 } from "@lucide/svelte";
	import { tableFromJSON, tableToIPC } from "apache-arrow";
	import AccessGraph from "./AccessGraph.svelte";
	import { fetchProducers } from "./api";
	import { deriveQuality, type QualityBadge } from "./quality";
	import GrantsPanel from "./GrantsPanel.svelte";
	import ReadersPanel from "./ReadersPanel.svelte";
	import {
		addColumn,
		compactTable,
		createTableBranch,
		createTableIndex,
		createTableTag,
		deleteTableBranch,
		deleteTablePolicy,
		deleteTableTag,
		dropColumn,
		dropTableIndex,
		moveTableTag,
		renameColumn,
		type CatalogResult,
		fetchTableDetail,
		type GcPreview,
		insertRows,
		partErrored,
		type Policy,
		type PolicyRequest,
		previewMaintenance,
		type TableStats,
		type TableDetail,
		restoreTableVersion,
		runMaintenance,
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
		target: number | null; // #76 target_rows_per_fragment
		enabled: boolean;
	}>({ retention_days: null, retain_versions: null, interval: null, target: null, enabled: true });

	// #64 version management — name (tag) a Lance version (writer-gated). Reset on table change below.
	let tagName = $state("");
	let tagVersion = $state(""); // the bits-ui Select value is a string; parsed to a number on submit
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

	// #64 data-plane row insert — append JSON rows, browser-encoded to Arrow via apache-arrow. Writer-gated.
	let insertJson = $state("");
	let insertBusy = $state(false);
	let insertMsg = $state<{ ok: boolean; text: string } | null>(null);

	// #81 the SvelteFlow authorization graph is lazy-mounted (heavy) behind this toggle.
	let showGraph = $state(false);

	// scope #6 quality gate — the validator's latest dataQualityAssertions verdict for this dataset, from
	// the lineage service's producing runs (medallion stages record it; a plain catalog table has none).
	let quality = $state<QualityBadge>(null);

	async function loadQuality(): Promise<void> {
		const current = table;
		const res = await fetchProducers(current);
		if (table !== current) return; // latest-wins
		quality = deriveQuality(res);
	}

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
		tagVersion = "";
		tagError = null;
		restoreConfirm = null;
		restoreError = null;
		blobCol = "";
		blobRow = null;
		blobSrc = null;
		blobFailed = false;
		insertJson = "";
		insertMsg = null;
		showGraph = false;
		gcDays = null;
		gcKeep = null;
		gcPreview = null;
		gcResult = null;
		gcError = null;
		gcConfirm = false;
		compactResult = null;
		colBusy = false;
		colError = null;
		addColName = "";
		addColExpr = "";
		renaming = null;
		renameTo = "";
		refBusy = false;
		refError = null;
		movingTag = null;
		moveTo = "";
		newBranch = "";
		newBranchFrom = "";
		quality = null;
		load();
		loadQuality();
	});

	function startPolicyEdit(): void {
		draft = {
			retention_days: policy?.retention_days ?? null,
			retain_versions: policy?.retain_versions ?? null,
			interval: policy?.compact_interval_hours ?? null,
			target: policy?.target_rows_per_fragment ?? null,
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
			if (draft.target != null) body.target_rows_per_fragment = draft.target;
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

	// #75 on-demand GC — preview (dry-run reclaimable versions) + run (destructive, two-click confirm).
	let gcDays = $state<number | null>(null);
	let gcKeep = $state<number | null>(null);
	let gcBusy = $state(false);
	let gcPreview = $state<GcPreview | null>(null);
	let gcResult = $state<string | null>(null);
	let gcError = $state<string | null>(null);
	let gcConfirm = $state(false);
	const gcHasBound = $derived(gcDays != null || gcKeep != null);

	function gcFail(status: number, detail: string): void {
		if (status === 401) gcError = "Sign in to run garbage collection.";
		else if (status === 403) gcError = "Denied: GC needs the owner rung (can_drop).";
		else if (status === 422) gcError = "Set a retention-days and/or keep-last bound first.";
		else gcError = detail;
	}

	async function runGcPreview(): Promise<void> {
		if (gcBusy || !gcHasBound) return;
		gcBusy = true;
		gcError = null;
		gcResult = null;
		gcConfirm = false;
		try {
			const res = await previewMaintenance(table, {
				retention_days: gcDays,
				retain_versions: gcKeep,
			});
			if (res.ok) gcPreview = res.data;
			else gcFail(res.status, res.detail);
		} finally {
			gcBusy = false;
		}
	}

	async function runGc(): Promise<void> {
		if (gcBusy || !gcHasBound) return;
		gcBusy = true;
		gcError = null;
		try {
			const res = await runMaintenance(table, { retention_days: gcDays, retain_versions: gcKeep });
			if (res.ok) {
				gcResult = `Reclaimed ${res.data.old_versions_removed} version(s) · ${fmtBytes(res.data.bytes_removed)}.`;
				gcPreview = null;
				gcConfirm = false;
				await load(); // GC changed the version set — refresh
			} else gcFail(res.status, res.detail);
		} finally {
			gcBusy = false;
		}
	}

	// #74 schema evolution — add (name + SQL expr) / rename / drop columns (writer-gated).
	let colBusy = $state(false);
	let colError = $state<string | null>(null);
	let addColName = $state("");
	let addColExpr = $state("");
	let renaming = $state<string | null>(null); // the column currently being renamed
	let renameTo = $state("");

	function colFail(status: number, detail: string): void {
		if (status === 401) colError = "Sign in to change the schema.";
		else if (status === 403)
			colError = "Denied: schema changes need writer access (can_write_data).";
		else colError = detail;
	}

	async function runAddColumn(): Promise<void> {
		const name = addColName.trim();
		const expr = addColExpr.trim();
		if (colBusy || !name || !expr) return;
		colBusy = true;
		colError = null;
		try {
			const res = await addColumn(table, name, expr);
			if (res.ok) {
				addColName = "";
				addColExpr = "";
				await load();
			} else colFail(res.status, res.detail);
		} finally {
			colBusy = false;
		}
	}

	async function runDropColumn(name: string): Promise<void> {
		if (colBusy) return;
		colBusy = true;
		colError = null;
		try {
			const res = await dropColumn(table, name);
			if (res.ok) await load();
			else colFail(res.status, res.detail);
		} finally {
			colBusy = false;
		}
	}

	async function runRenameColumn(): Promise<void> {
		const from = renaming;
		const to = renameTo.trim();
		if (colBusy || !from || !to) return;
		colBusy = true;
		colError = null;
		try {
			const res = await renameColumn(table, from, to);
			if (res.ok) {
				renaming = null;
				renameTo = "";
				await load();
			} else colFail(res.status, res.detail);
		} finally {
			colBusy = false;
		}
	}

	// #74 ref-plane mutations — tag delete/move (owner can_update_tag) + branch create/delete.
	let refBusy = $state(false);
	let refError = $state<string | null>(null);
	let movingTag = $state<string | null>(null); // the tag currently being moved
	let moveTo = $state(""); // target version (bits-ui Select string)
	let newBranch = $state("");
	let newBranchFrom = $state(""); // optional source version (Select string)

	function refFail(status: number, detail: string): void {
		if (status === 401) refError = "Sign in to manage tags & branches.";
		else if (status === 403) refError = "Denied: managing refs needs writer/owner access.";
		else refError = detail;
	}

	async function refDo(fn: () => Promise<CatalogResult<unknown>>): Promise<void> {
		if (refBusy) return;
		refBusy = true;
		refError = null;
		try {
			const res = await fn();
			if (res.ok) await load();
			else refFail(res.status, res.detail);
		} finally {
			refBusy = false;
		}
	}

	const runDeleteTag = (name: string) => refDo(() => deleteTableTag(table, name));
	const runDeleteBranch = (name: string) => refDo(() => deleteTableBranch(table, name));

	async function runMoveTag(): Promise<void> {
		if (!movingTag || !moveTo) return;
		const name = movingTag;
		await refDo(() => moveTableTag(table, name, Number(moveTo)));
		movingTag = null;
		moveTo = "";
	}

	async function runCreateBranch(): Promise<void> {
		const name = newBranch.trim();
		if (!name) return;
		await refDo(() => createTableBranch(table, name, newBranchFrom ? Number(newBranchFrom) : null));
		newBranch = "";
		newBranchFrom = "";
	}

	// #76 compact-now — merge small fragments (non-destructive), using the policy's target size if set.
	let compactBusy = $state(false);
	let compactResult = $state<string | null>(null);

	async function runCompact(): Promise<void> {
		if (compactBusy) return;
		compactBusy = true;
		gcError = null;
		compactResult = null;
		try {
			const res = await compactTable(table, policy?.target_rows_per_fragment ?? null);
			if (res.ok) {
				compactResult = `Compacted · ${res.data.fragments_removed} fragment(s) → ${res.data.fragments_added}.`;
				await load(); // compaction wrote a new version — refresh
			} else gcFail(res.status, res.detail);
		} finally {
			compactBusy = false;
		}
	}

	async function runTag(): Promise<void> {
		const name = tagName.trim();
		if (tagBusy || !name || !tagVersion) return;
		tagBusy = true;
		tagError = null;
		try {
			const res = await createTableTag(table, name, Number(tagVersion));
			if (res.ok) {
				tagName = "";
				tagVersion = "";
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

	async function runInsert(): Promise<void> {
		if (insertBusy || !insertJson.trim()) return;
		insertBusy = true;
		insertMsg = null;
		let rows: Record<string, unknown>[];
		try {
			const parsed: unknown = JSON.parse(insertJson);
			if (!Array.isArray(parsed) || parsed.length === 0) {
				throw new Error("expected a non-empty JSON array of row objects");
			}
			rows = parsed as Record<string, unknown>[];
		} catch (e) {
			insertMsg = {
				ok: false,
				text: `Invalid rows: ${e instanceof Error ? e.message : String(e)}`,
			};
			insertBusy = false;
			return;
		}
		try {
			// Browser-side Arrow-IPC encode (apache-arrow) → the catalog's Arrow-body insert. The inferred
			// schema must match the table's — a mismatch is the catalog's honest error, surfaced below.
			const arrow = tableToIPC(tableFromJSON(rows), "stream");
			const res = await insertRows(table, arrow);
			if (res.ok) {
				insertMsg = {
					ok: true,
					text: `Inserted ${rows.length} row${rows.length === 1 ? "" : "s"}.`,
				};
				insertJson = "";
				await load(); // the insert bumped the version — refresh stats + versions
			} else if (res.status === 401) {
				insertMsg = { ok: false, text: "Sign in to insert rows." };
			} else if (res.status === 403) {
				insertMsg = {
					ok: false,
					text: "Denied: inserting rows needs writer access (can_write_data).",
				};
			} else {
				insertMsg = { ok: false, text: res.detail };
			}
		} catch (e) {
			insertMsg = {
				ok: false,
				text: `Encode failed: ${e instanceof Error ? e.message : String(e)}`,
			};
		} finally {
			insertBusy = false;
		}
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
			name: string;
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

	// #73 index management — build (scalar / vector) + drop. Vector indexes (IVF/HNSW) are the Lance
	// differentiator neither Iceberg nor Unity has; a rebuild is a create with the same column (Lance
	// replaces). The catalog gates all three at the writer tier (can_write_data).
	const SCALAR_TYPES = ["BTREE", "BITMAP", "INVERTED", "NGRAM"];
	const VECTOR_TYPES = ["IVF_PQ", "IVF_HNSW_SQ"];
	let ixColumn = $state("");
	let ixType = $state("BTREE");
	let ixDistance = $state("cosine");
	let ixBusy = $state(false);
	let ixError = $state<string | null>(null);
	const ixScalar = $derived(SCALAR_TYPES.includes(ixType));

	async function runCreateIndex(): Promise<void> {
		const column = ixColumn.trim();
		if (ixBusy || !column || !ixType) return;
		ixBusy = true;
		ixError = null;
		try {
			const body = ixScalar
				? { column, index_type: ixType }
				: { column, index_type: ixType, distance_type: ixDistance };
			const res = await createTableIndex(table, body, ixScalar);
			if (res.ok) {
				ixColumn = "";
				await load(); // pull the new index into the list (the build bumps the version too)
			} else if (res.status === 401) {
				ixError = "Sign in to build an index.";
			} else if (res.status === 403) {
				ixError = "Denied: building an index needs writer access (can_write_data).";
			} else {
				ixError = res.detail;
			}
		} finally {
			ixBusy = false;
		}
	}

	async function runDropIndex(name: string | undefined): Promise<void> {
		if (ixBusy || !name) return;
		ixBusy = true;
		ixError = null;
		try {
			const res = await dropTableIndex(table, name);
			if (res.ok) {
				await load();
			} else if (res.status === 401) {
				ixError = "Sign in to drop an index.";
			} else if (res.status === 403) {
				ixError = "Denied: dropping an index needs writer access (can_write_data).";
			} else {
				ixError = res.detail;
			}
		} finally {
			ixBusy = false;
		}
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
					<!-- #78 the catalog's fixed file format (Lance columnar, storage 2.2) — never a silent guess. -->
					{#if detail.format}
						<span
							class="fmt"
							title="This catalog stores Lance only; format-selecting properties are rejected."
							>{detail.format.name} · storage v{detail.format.storage_version}</span
						>
					{/if}
					<!-- scope #6 quality gate — the validator's dataQualityAssertions verdict on the latest
					     producing run (from lineage). A plain catalog table has none, stated honestly. -->
					{#if quality}
						<span
							class="qual {quality.passed ? 'ok' : 'bad'}"
							title="Validator dataQualityAssertions on the latest producing run (lineage)."
							>quality {quality.passed ? "passed" : "blocked"}{quality.assertions
								? ` · ${quality.assertions} check${quality.assertions === 1 ? "" : "s"}`
								: ""}</span
						>
					{:else}
						<span class="qual none" title="No producing run has recorded dataQualityAssertions."
							>no quality gate</span
						>
					{/if}
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
					<thead><tr><th>field</th><th>type</th><th>nullable</th><th></th></tr></thead>
					<tbody>
						{#each schemaFields as f (f.name)}
							<tr>
								<td class="mono">{f.name}</td>
								<td class="mono">{typeName(f.type)}</td>
								<td class="mono">{f.nullable ? "yes" : "no"}</td>
								<td class="actions">
									{#if renaming === f.name}
										<input
											class="mono rn"
											bind:value={renameTo}
											placeholder="new name"
											aria-label="rename {f.name} to"
											onkeydown={(e) => e.key === "Enter" && runRenameColumn()}
										/>
										<button
											class="btn ghost"
											disabled={colBusy || !renameTo.trim()}
											onclick={runRenameColumn}>save</button
										>
										<button class="btn ghost" onclick={() => (renaming = null)}>×</button>
									{:else}
										<button
											class="chip-x"
											title="rename column"
											aria-label="rename {f.name}"
											disabled={colBusy}
											onclick={() => {
												renaming = f.name;
												renameTo = "";
											}}>✎</button
										>
										<button
											class="chip-x"
											title="drop column"
											aria-label="drop {f.name}"
											disabled={colBusy}
											onclick={() => runDropColumn(f.name)}>×</button
										>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
			<!-- #74 add a SQL-expression column (e.g. price * 2, cast(null as int)). Writer-gated. -->
			<form
				class="row addcol"
				onsubmit={(e) => {
					e.preventDefault();
					runAddColumn();
				}}
			>
				<input
					class="mono"
					bind:value={addColName}
					placeholder="new column"
					aria-label="New column name"
				/>
				<input
					class="mono"
					bind:value={addColExpr}
					placeholder="SQL expression (e.g. cast(null as int))"
					aria-label="Column SQL expression"
				/>
				<button
					class="btn"
					type="submit"
					disabled={colBusy || !addColName.trim() || !addColExpr.trim()}
				>
					Add column
				</button>
			</form>
			{#if colError}<p class="error">{colError}</p>{/if}
		</section>

		<section>
			<h2>Insert rows</h2>
			<p class="mut">Append rows as a JSON array of objects whose keys match the schema.</p>
			<textarea class="mono ins" bind:value={insertJson} placeholder={'[{ "id": 1, "name": "a" }]'}
			></textarea>
			<div class="ins-row">
				<button class="btn" disabled={insertBusy || !insertJson.trim()} onclick={runInsert}>
					{insertBusy ? "…" : "Insert"}
				</button>
				{#if insertMsg}<span class="ins-msg" class:okmsg={insertMsg.ok} class:error={!insertMsg.ok}
						>{insertMsg.text}</span
					>{/if}
			</div>
		</section>

		<section>
			<h2>Blob preview</h2>
			{#if blobColumns.length === 0}
				<p class="mut">No blob columns on this table.</p>
			{:else}
				<div class="refs tagform">
					<Select
						bind:value={blobCol}
						ariaLabel="Blob column"
						placeholder="column…"
						options={blobColumns.map((c) => ({ value: c, label: c }))}
					/>
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
							>
							<button
								class="chip-x"
								title="drop index"
								aria-label="drop index {ix.index_name}"
								disabled={ixBusy}
								onclick={() => runDropIndex(ix.index_name)}>×</button
							></span
						>
					{/each}
				</div>
			{/if}
			<!-- #73 build an index — scalar (BTREE/BITMAP/INVERTED/NGRAM) or vector (IVF/HNSW). Writer-gated. -->
			<form
				class="row"
				onsubmit={(e) => {
					e.preventDefault();
					runCreateIndex();
				}}
			>
				<input class="mono" bind:value={ixColumn} placeholder="column" aria-label="Index column" />
				<Select
					bind:value={ixType}
					ariaLabel="Index type"
					options={[
						...SCALAR_TYPES.map((t) => ({ value: t, label: `scalar · ${t}` })),
						...VECTOR_TYPES.map((t) => ({ value: t, label: `vector · ${t}` })),
					]}
				/>
				{#if !ixScalar}
					<Select
						bind:value={ixDistance}
						ariaLabel="Distance type"
						options={[
							{ value: "cosine", label: "cosine" },
							{ value: "l2", label: "l2" },
							{ value: "dot", label: "dot" },
						]}
					/>
				{/if}
				<button class="btn" type="submit" disabled={ixBusy || !ixColumn.trim()}>
					{ixBusy ? "…" : "Build index"}
				</button>
			</form>
			{#if ixError}<p class="error">{ixError}</p>{/if}
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
				<span class="chip mono">main</span>
				{#each branches as [name, b] (name)}
					<span class="chip branch mono"
						>{name}<span class="mut"> · {fmtBytes(b.manifestSize)}</span>
						<button
							class="chip-x"
							title="delete branch"
							aria-label="delete branch {name}"
							disabled={refBusy}
							onclick={() => runDeleteBranch(name)}>×</button
						></span
					>
				{/each}
			</div>
			<!-- #74 create a branch from a version (owner-gated can_create_branch). -->
			<form
				class="row addcol"
				onsubmit={(e) => {
					e.preventDefault();
					runCreateBranch();
				}}
			>
				<input
					class="mono"
					bind:value={newBranch}
					placeholder="new branch"
					aria-label="New branch name"
				/>
				<Select
					bind:value={newBranchFrom}
					ariaLabel="Branch from version"
					placeholder="from version (latest)"
					options={versions.map((v) => ({ value: String(v.version), label: `v${v.version}` }))}
				/>
				<button class="btn" type="submit" disabled={refBusy || !newBranch.trim()}
					>Create branch</button
				>
			</form>

			<div class="refs">
				{#if tags.length === 0}
					<span class="mut">No tags — a promotion pins its version with one (e.g. blessed).</span>
				{:else}
					{#each tags as [name, t] (name)}
						{#if movingTag === name}
							<span class="chip tag mono">
								{name} →
								<span class="movesel">
									<Select
										bind:value={moveTo}
										ariaLabel="move {name} to version"
										placeholder="version"
										options={versions.map((v) => ({
											value: String(v.version),
											label: `v${v.version}`,
										}))}
									/>
								</span>
								<button class="chip-x" disabled={refBusy || !moveTo} onclick={runMoveTag}
									>save</button
								>
								<button class="chip-x" onclick={() => (movingTag = null)}>×</button>
							</span>
						{:else}
							<span class="chip tag mono"
								>{name} → v{t.version}
								<button
									class="chip-x"
									title="move tag"
									aria-label="move tag {name}"
									disabled={refBusy}
									onclick={() => {
										movingTag = name;
										moveTo = "";
									}}>↪</button
								>
								<button
									class="chip-x"
									title="delete tag"
									aria-label="delete tag {name}"
									disabled={refBusy}
									onclick={() => runDeleteTag(name)}>×</button
								></span
							>
						{/if}
					{/each}
				{/if}
			</div>
			{#if refError}<p class="error">{refError}</p>{/if}

			{#if versions.length > 0}
				<div class="refs tagform">
					<input class="mono" placeholder="tag name (e.g. blessed)" bind:value={tagName} />
					<Select
						bind:value={tagVersion}
						ariaLabel="Version to tag"
						placeholder="version…"
						options={versions.map((v) => ({ value: String(v.version), label: `v${v.version}` }))}
					/>
					<button class="btn" disabled={tagBusy || !tagName.trim() || !tagVersion} onclick={runTag}>
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
					<label
						>target rows/fragment <input
							class="mono"
							type="number"
							min="1024"
							bind:value={draft.target}
							placeholder="Lance default"
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
					{#if policy.target_rows_per_fragment}<span class="chip mono"
							>target {policy.target_rows_per_fragment} rows/frag</span
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

			<!-- #75 on-demand GC: dry-run reclaimable versions, then reclaim (owner-gated, destructive). -->
			<div class="gc">
				<h3>Garbage collection</h3>
				<div class="row">
					<label
						>older than (days) <input
							class="mono"
							type="number"
							min="1"
							bind:value={gcDays}
							placeholder="any age"
						/></label
					>
					<label
						>keep last <input
							class="mono"
							type="number"
							min="1"
							bind:value={gcKeep}
							placeholder="—"
						/></label
					>
					<button class="btn ghost" disabled={gcBusy || !gcHasBound} onclick={runGcPreview}>
						Preview
					</button>
				</div>
				{#if gcPreview}
					<p class="mut">
						{gcPreview.eligible_versions.length} version{gcPreview.eligible_versions.length === 1
							? ""
							: "s"} reclaimable
						{#if gcPreview.eligible_versions.length}(v{gcPreview.eligible_versions.join(
								", v",
							)}){/if}
						· {gcPreview.total_versions} total, current v{gcPreview.current_version}.
						{#if Object.keys(gcPreview.protected_tags).length}
							Protected by tags: {Object.entries(gcPreview.protected_tags)
								.map(([t, v]) => `${t}→v${v}`)
								.join(", ")}.
						{/if}
					</p>
					{#if gcPreview.eligible_versions.length}
						{#if gcConfirm}
							<div class="row">
								<span class="mut"
									>Permanently reclaim {gcPreview.eligible_versions.length} version(s)?</span
								>
								<button class="btn danger" disabled={gcBusy} onclick={runGc}>Confirm reclaim</button
								>
								<button class="btn ghost" onclick={() => (gcConfirm = false)}>Cancel</button>
							</div>
						{:else}
							<button class="btn" disabled={gcBusy} onclick={() => (gcConfirm = true)}>
								<Trash2 size={12} /> Reclaim now
							</button>
						{/if}
					{/if}
				{/if}
				{#if gcResult}<p class="mut">{gcResult}</p>{/if}

				<!-- #76 compact-now: merge small fragments (non-destructive), using the policy's target size. -->
				<div class="row gc-compact">
					<button class="btn ghost" disabled={compactBusy} onclick={runCompact}>
						{compactBusy ? "compacting…" : "Compact now"}
					</button>
					{#if compactResult}<span class="mut">{compactResult}</span>{/if}
				</div>
				{#if gcError}<p class="error">{gcError}</p>{/if}
			</div>
		</section>

		<section>
			<h2>Access</h2>
			<GrantsPanel dataset={table} />
			<ReadersPanel dataset={table} />
			<!-- #81 the relationship graph is heavy (SvelteFlow) — lazy-mount behind a toggle. -->
			<button class="btn ghost graphtoggle" onclick={() => (showGraph = !showGraph)}>
				{showGraph ? "Hide" : "Show"} authorization graph
			</button>
			{#if showGraph}<AccessGraph dataset={table} />{/if}
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
	.fmt {
		border: 1px solid color-mix(in srgb, var(--accent, #ffc14d) 45%, var(--line));
		border-radius: var(--radius-sm);
		padding: 0 6px;
		color: var(--mut);
	}
	.qual {
		border-radius: var(--radius-sm);
		padding: 0 6px;
		border: 1px solid var(--line);
	}
	.qual.ok {
		color: var(--ok);
		border-color: color-mix(in srgb, var(--ok) 45%, var(--line));
	}
	.qual.bad {
		color: var(--fail);
		border-color: color-mix(in srgb, var(--fail) 45%, var(--line));
	}
	.qual.none {
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
	.chip-x {
		margin-left: 5px;
		background: none;
		border: none;
		padding: 0;
		color: var(--faint);
		font: inherit;
		cursor: pointer;
	}
	td.actions {
		text-align: right;
		white-space: nowrap;
	}
	.rn {
		width: 110px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 2px 6px;
	}
	.addcol {
		margin-top: 10px;
	}
	.chip-x:hover {
		color: var(--fail);
	}
	.chip-x:disabled {
		opacity: 0.4;
		cursor: default;
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
	.policy-edit input[type="number"],
	.gc input[type="number"] {
		width: 110px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		padding: 4px 8px;
		font-size: 12px;
	}
	.gc {
		margin-top: 14px;
		padding-top: 12px;
		border-top: 1px solid color-mix(in srgb, var(--line) 45%, transparent);
	}
	.gc h3 {
		font-size: 13px;
		margin: 0 0 8px;
	}
	.gc label {
		display: inline-flex;
		flex-direction: column;
		gap: 3px;
		font-size: 12px;
		color: var(--mut);
	}
	.gc-compact {
		align-items: center;
		margin-top: 8px;
	}
	.tagform input,
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
	.ins {
		width: 100%;
		min-height: 72px;
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-sm);
		color: var(--ink);
		font-size: 12px;
		padding: 7px 9px;
		resize: vertical;
	}
	.ins-row {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 6px;
	}
	.ins-msg {
		font-size: 12px;
	}
	.okmsg {
		color: var(--ok);
	}
	.btn.ghost {
		background: none;
		color: var(--mut);
	}
	.graphtoggle {
		margin: 10px 0 8px;
	}
	.btn.danger {
		color: var(--fail);
	}
	.row {
		display: flex;
		gap: 8px;
	}
</style>
