// Typed client for the CATALOG service via the /capi BFF proxy (the /api proxy covers lineage).
// Types are generated from docs/catalog-openapi.json (`bun run gen:types:catalog`) — never hand-mirrored.
// The describe route serializes with response_model_exclude_none, so its null fields arrive absent —
// read optional fields with `?? null` rather than trusting the generated required-nullable shape.
import type { components } from '@rask/api/generated/catalog';
import { type ApiResult, requestJSON as request } from '$lib/http';

export type ModelSummary = components['schemas']['ModelSummary'];
export type ModelsList = components['schemas']['ModelsListResponse'];
export type ModelDescribe = components['schemas']['ModelDescribeResponse'];
/** One object under the model's artifact tree (path relative to the model root) — the describe
 * response's `artifacts` listing the registry detail renders as a table. */
export type ModelArtifact = components['schemas']['ModelArtifact'];
export type PromoteResponse = components['schemas']['PromoteResponse'];
export type AccessList = components['schemas']['AccessListResponse'];
export type AccessCheck = components['schemas']['AccessCheckResponse'];
export type TableDescribe = components['schemas']['DescribeTableResponse'];
export type TableStats = components['schemas']['GetTableStatsResponse'];
export type TableVersions = components['schemas']['ListTableVersionsResponse'];
export type TableTags = components['schemas']['ListTableTagsResponse'];
export type TableBranches = components['schemas']['ListTableBranchesResponse'];
export type TableIndexes = components['schemas']['ListTableIndicesResponse'];
export type Policy = components['schemas']['PolicyResponse'];
export type PolicyRequest = components['schemas']['PolicyRequest'];
export type Warehouse = components['schemas']['WarehouseResponse'];
export type CreateWarehouse = components['schemas']['CreateWarehouseRequest'];

/** A part the BFF could not resolve: `null` means genuinely absent (404 — e.g. no policy set),
 * `{ error }` means a transient upstream failure (5xx/403) — the page renders "unavailable" for the
 * latter, never an affirmative "none" that would invite an overwriting write. */
export type PartError = { error: number };
export function partErrored<T>(part: T | PartError | null): part is PartError {
	return part !== null && typeof part === 'object' && 'error' in part;
}

/** The detail-page aggregate the /capi/v1/table/{id}/detail BFF route assembles server-side —
 * `describe` gates the whole page (its failure is the page status), the rest are per-part optional. */
export type TableDetail = {
	describe: TableDescribe;
	stats: TableStats | PartError | null;
	versions: TableVersions | PartError | null;
	tags: TableTags | PartError | null;
	branches: TableBranches | PartError | null;
	indexes: TableIndexes | PartError | null;
	policy: Policy | PartError | null;
	format?: { name: string; storage_version: string }; // #78 the catalog's fixed Lance file format
};

/** Compatibility alias — the status-aware Result shape now lives in http.ts, shared with the lineage client. */
export type CatalogResult<T> = ApiResult<T>;

const requestJSON = <T>(path: string, init?: RequestInit) => request<T>('/capi', path, init);

const enc = encodeURIComponent;

export const fetchModels = () => requestJSON<ModelsList>('v1/model');
export const fetchModel = (model: string) => requestJSON<ModelDescribe>(`v1/model/${enc(model)}`);

/** Bless `version` of `model` (candidate→blessed). Carries the signed-in user's session only — the BFF
 * refuses an anonymous promote outright (401) without forwarding anything. */
export const promoteModel = (model: string, version: number) =>
	requestJSON<PromoteResponse>(`v1/model/${enc(model)}/promote`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ version }),
	});

/** Access review (#51): who holds which can_* action on the table. Owner-gated by the catalog
 * (403 for non-owners); the BFF forwards only the signed-in user's session. */
export const fetchTableAccess = (table: string) =>
	requestJSON<AccessList>(`v1/table/${enc(table)}/access/list`, { method: 'POST' });

/** #68 "who can do what" simulator — a live OpenFGA Check: does `user` hold `relation` on this table?
 * Owner-gated by the catalog (can_drop), the same bar as the review (probing the graph == disclosing it). */
export const checkTableAccess = (table: string, user: string, relation: string) =>
	requestJSON<AccessCheck>(`v1/table/${enc(table)}/access/check`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ user, relation }),
	});

export type AccessGrant = components['schemas']['AccessGrantResponse'];

/** #72 grant a base rung (owner/writer/reader/validator) to a subject on the table. `user` may be a bare
 * id (`alice`) or a userset (`role:…#assignee` / `team:…#member`). Owner-gated by the catalog (can_drop);
 * the BFF forwards only the signed-in user's session. */
export const grantTableAccess = (table: string, user: string, relation: string) =>
	requestJSON<AccessGrant>(`v1/table/${enc(table)}/access/grant`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ user, relation }),
	});
/** #72 revoke a base rung from a subject on the table — the write counterpart of the grant, same gate. */
export const revokeTableAccess = (table: string, user: string, relation: string) =>
	requestJSON<AccessGrant>(`v1/table/${enc(table)}/access/revoke`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ user, relation }),
	});

export type AccessGraph = components['schemas']['AccessGraphResponse'];

/** #81 one hop of the authorization graph around the table — its direct grantees + the parent edge, for the
 * SvelteFlow relationship explorer. Owner-gated by the catalog (can_drop); session-only BFF. */
export const fetchAccessGraph = (table: string) =>
	requestJSON<AccessGraph>(`v1/table/${enc(table)}/access/graph`, { method: 'POST' });

export type TablesList = components['schemas']['ListTablesResponse'];

/** The catalog's own table registry (#52) — names in `<ns>$<table>` canonical form. */
export const fetchTables = () => requestJSON<TablesList>('v1/table');

/** One-round-trip detail aggregate for the table page (schema/stats/versions/tags/policy). */
export const fetchTableDetail = (table: string) =>
	requestJSON<TableDetail>(`v1/table/${enc(table)}/detail`);

/** Maintenance-policy writes (#50 UI): owner-gated by the catalog (can_drop), session-only BFF. */
export const setTablePolicy = (table: string, policy: PolicyRequest) =>
	requestJSON<Policy>(`v1/table/${enc(table)}/policy`, {
		method: 'PUT',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(policy),
	});
export const deleteTablePolicy = (table: string) =>
	requestJSON<{ status: string }>(`v1/table/${enc(table)}/policy`, { method: 'DELETE' });

export type GcBounds = { retention_days?: number | null; retain_versions?: number | null };
export type GcPreview = components['schemas']['GcPreview'];
export type GcRunResult = components['schemas']['GcRunResult'];

/** #75 dry-run GC — the versions reclaimable under these bounds + the tags protecting others. Owner-gated
 * (can_drop), session-only BFF. Never mutates. */
export const previewMaintenance = (table: string, bounds: GcBounds) =>
	requestJSON<GcPreview>(`v1/table/${enc(table)}/maintenance/preview`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(bounds),
	});
/** #75 reclaim old versions on demand (destructive; tag-pinned versions exempt). Owner-gated. */
export const runMaintenance = (table: string, bounds: GcBounds) =>
	requestJSON<GcRunResult>(`v1/table/${enc(table)}/maintenance/run`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(bounds),
	});

export type CompactResult = components['schemas']['CompactResult'];

/** #76 compact small fragments on demand (non-destructive — writes a new version). Optional
 * target_rows_per_fragment overrides the sizing. Owner-gated (can_drop), session-only BFF. */
export const compactTable = (table: string, targetRowsPerFragment?: number | null) =>
	requestJSON<CompactResult>(`v1/table/${enc(table)}/maintenance/compact`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ target_rows_per_fragment: targetRowsPerFragment ?? null }),
	});

/** #64 version management — name (tag) a Lance version. Writer-gated (can_create_tag) by the catalog,
 * session-only BFF. A promotion pins its version with a tag; this is the manual equivalent. */
export const createTableTag = (table: string, tag: string, version: number) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/tags`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ tag, version }),
	});

/** #74 delete a tag (writer-gated). */
export const deleteTableTag = (table: string, tag: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/tags/delete`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ tag }),
	});
/** #74 move a tag to another version (owner-gated can_update_tag). */
export const moveTableTag = (table: string, tag: string, version: number) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/tags/update`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ tag, version }),
	});
/** #74 create a branch from a version (owner-gated can_create_branch). */
export const createTableBranch = (table: string, name: string, fromVersion?: number | null) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/branches/create`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ name, from_version: fromVersion ?? null }),
	});
/** #74 delete a branch (writer-gated). */
export const deleteTableBranch = (table: string, name: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/branches/delete`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ name }),
	});

/** #64 version management — restore the table to a prior version. Restore mints a FRESH version pointing
 * at the restored data (history is never rewritten); owner-gated (can_restore), session-only BFF. */
export const restoreTableVersion = (table: string, version: number) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/restore`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ version }),
	});

/** #64 data-plane row insert — append Arrow-IPC rows (built in the browser via apache-arrow). Writer-gated
 * (can_write_data) at the catalog, session-only BFF. `mode=append` never rewrites existing versions. */
export const insertRows = (table: string, arrow: Uint8Array) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/insert?mode=append`, {
		method: 'POST',
		headers: { 'content-type': 'application/vnd.apache.arrow.stream' },
		body: arrow as BodyInit,
	});

/** #74 schema evolution — add a SQL-expression column. Writer-gated (can_write_data), session-only BFF. */
export const addColumn = (table: string, name: string, expression: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/add`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ new_columns: [{ name, expression }] }),
	});
/** #74 rename an existing column (alter_columns path→rename). Writer-gated, session-only BFF. */
export const renameColumn = (table: string, path: string, rename: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/alter`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ alterations: [{ path, rename }] }),
	});
/** #74 drop a column. Writer-gated, session-only BFF. */
export const dropColumn = (table: string, name: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/drop`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ columns: [name] }),
	});

/** #74 tail — the scalar Arrow types the catalog's `_SCALAR_ARROW` map accepts as an alter_columns re-type
 * target. A cast Lance can't perform (e.g. string→int on non-numeric text) 400s at the catalog, surfaced. */
export const RETYPE_TYPES = [
	'int8',
	'int16',
	'int32',
	'int64',
	'uint8',
	'uint16',
	'uint32',
	'uint64',
	'float16',
	'float32',
	'float64',
	'string',
	'large_string',
	'bool',
	'date32',
	'date64',
	'binary',
	'large_binary',
] as const;

/** #74 tail — re-type an existing column (alter_columns path→data_type). Writer-gated, session-only BFF. */
export const retypeColumn = (table: string, path: string, type: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/alter`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ alterations: [{ path, data_type: { type } }] }),
	});

/** #74 tail — merge or replace one field's metadata (update_field_metadata). A `null` value deletes that key.
 * Writer-gated (can_write_data) at the catalog; session-only BFF. */
export const setFieldMetadata = (
	table: string,
	path: string,
	metadata: Record<string, string | null>,
	replace = false,
) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/field-meta`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ updates: [{ path, metadata, replace }] }),
	});

/** #74 tail — SET the table's schema-level metadata map (schema_metadata/update replaces the whole map, so
 * the caller sends the full desired map). Writer-gated (can_write_data) at the catalog; session-only BFF. */
export const setTableProperties = (table: string, metadata: Record<string, string>) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/columns/table-meta`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ metadata }),
	});

export type CreateIndexBody = { column: string; index_type: string; distance_type?: string };

/** #73 build an index — `scalar` picks the catalog's create_scalar_index (BTREE/BITMAP/INVERTED …) vs
 * create_index (the IVF/HNSW vector families). A rebuild is just a create with the same column (Lance
 * replaces the existing one). Writer-gated (can_write_data) at the catalog; session-only BFF. */
export const createTableIndex = (table: string, body: CreateIndexBody, scalar: boolean) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/index/create?scalar=${scalar ? 1 : 0}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body),
	});
/** #73 drop a named index — writer-gated (can_write_data), session-only BFF. */
export const dropTableIndex = (table: string, name: string) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/index/${enc(name)}/drop`, { method: 'POST' });

/** Warehouse admin (#3-A UI): reads for any signed-in user the catalog allows; writes are
 * project-admin gated by the catalog (can_create_warehouse / can_administer). */
export const fetchWarehouses = () => requestJSON<Warehouse[]>('v1/warehouses');
export const createWarehouse = (body: CreateWarehouse) =>
	requestJSON<Warehouse>('v1/warehouses', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body),
	});
export const setWarehouseActive = (id: string, active: boolean) =>
	requestJSON<Warehouse>(`v1/warehouses/${enc(id)}/${active ? 'activate' : 'deactivate'}`, {
		method: 'POST',
	});
export const bindWarehouseNamespace = (id: string, namespace: string) =>
	requestJSON<unknown>(`v1/warehouses/${enc(id)}/namespaces`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ namespace }),
	});
