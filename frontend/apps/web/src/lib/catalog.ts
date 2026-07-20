// Typed client for the CATALOG service via the /capi BFF proxy (the /api proxy covers lineage).
// Types are generated from docs/catalog-openapi.json (`bun run gen:types:catalog`) — never hand-mirrored.
// The describe route serializes with response_model_exclude_none, so its null fields arrive absent —
// read optional fields with `?? null` rather than trusting the generated required-nullable shape.
import type { components } from "./catalog.generated";
import { type ApiResult, requestJSON as request } from "./http";

export type ModelSummary = components["schemas"]["ModelSummary"];
export type ModelsList = components["schemas"]["ModelsListResponse"];
export type ModelDescribe = components["schemas"]["ModelDescribeResponse"];
export type PromoteResponse = components["schemas"]["PromoteResponse"];
export type AccessList = components["schemas"]["AccessListResponse"];
export type AccessCheck = components["schemas"]["AccessCheckResponse"];
export type TableDescribe = components["schemas"]["DescribeTableResponse"];
export type TableStats = components["schemas"]["GetTableStatsResponse"];
export type TableVersions = components["schemas"]["ListTableVersionsResponse"];
export type TableTags = components["schemas"]["ListTableTagsResponse"];
export type TableBranches = components["schemas"]["ListTableBranchesResponse"];
export type TableIndexes = components["schemas"]["ListTableIndicesResponse"];
export type Policy = components["schemas"]["PolicyResponse"];
export type PolicyRequest = components["schemas"]["PolicyRequest"];
export type Warehouse = components["schemas"]["WarehouseResponse"];
export type CreateWarehouse = components["schemas"]["CreateWarehouseRequest"];

/** A part the BFF could not resolve: `null` means genuinely absent (404 — e.g. no policy set),
 * `{ error }` means a transient upstream failure (5xx/403) — the page renders "unavailable" for the
 * latter, never an affirmative "none" that would invite an overwriting write. */
export type PartError = { error: number };
export function partErrored<T>(part: T | PartError | null): part is PartError {
	return part !== null && typeof part === "object" && "error" in part;
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
};

/** Compatibility alias — the status-aware Result shape now lives in http.ts, shared with the lineage client. */
export type CatalogResult<T> = ApiResult<T>;

const requestJSON = <T>(path: string, init?: RequestInit) => request<T>("/capi", path, init);

const enc = encodeURIComponent;

export const fetchModels = () => requestJSON<ModelsList>("v1/model");
export const fetchModel = (model: string) => requestJSON<ModelDescribe>(`v1/model/${enc(model)}`);

/** Bless `version` of `model` (candidate→blessed). Carries the signed-in user's session only — the BFF
 * refuses an anonymous promote outright (401) without forwarding anything. */
export const promoteModel = (model: string, version: number) =>
	requestJSON<PromoteResponse>(`v1/model/${enc(model)}/promote`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ version }),
	});

/** Access review (#51): who holds which can_* action on the table. Owner-gated by the catalog
 * (403 for non-owners); the BFF forwards only the signed-in user's session. */
export const fetchTableAccess = (table: string) =>
	requestJSON<AccessList>(`v1/table/${enc(table)}/access/list`, { method: "POST" });

/** #68 "who can do what" simulator — a live OpenFGA Check: does `user` hold `relation` on this table?
 * Owner-gated by the catalog (can_drop), the same bar as the review (probing the graph == disclosing it). */
export const checkTableAccess = (table: string, user: string, relation: string) =>
	requestJSON<AccessCheck>(`v1/table/${enc(table)}/access/check`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ user, relation }),
	});

export type TablesList = components["schemas"]["ListTablesResponse"];

/** The catalog's own table registry (#52) — names in `<ns>$<table>` canonical form. */
export const fetchTables = () => requestJSON<TablesList>("v1/table");

/** One-round-trip detail aggregate for the table page (schema/stats/versions/tags/policy). */
export const fetchTableDetail = (table: string) =>
	requestJSON<TableDetail>(`v1/table/${enc(table)}/detail`);

/** Maintenance-policy writes (#50 UI): owner-gated by the catalog (can_drop), session-only BFF. */
export const setTablePolicy = (table: string, policy: PolicyRequest) =>
	requestJSON<Policy>(`v1/table/${enc(table)}/policy`, {
		method: "PUT",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(policy),
	});
export const deleteTablePolicy = (table: string) =>
	requestJSON<{ status: string }>(`v1/table/${enc(table)}/policy`, { method: "DELETE" });

/** #64 version management — name (tag) a Lance version. Writer-gated (can_create_tag) by the catalog,
 * session-only BFF. A promotion pins its version with a tag; this is the manual equivalent. */
export const createTableTag = (table: string, tag: string, version: number) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/tags`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ tag, version }),
	});

/** #64 version management — restore the table to a prior version. Restore mints a FRESH version pointing
 * at the restored data (history is never rewritten); owner-gated (can_restore), session-only BFF. */
export const restoreTableVersion = (table: string, version: number) =>
	requestJSON<unknown>(`v1/table/${enc(table)}/restore`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ version }),
	});

/** Warehouse admin (#3-A UI): reads for any signed-in user the catalog allows; writes are
 * project-admin gated by the catalog (can_create_warehouse / can_administer). */
export const fetchWarehouses = () => requestJSON<Warehouse[]>("v1/warehouses");
export const createWarehouse = (body: CreateWarehouse) =>
	requestJSON<Warehouse>("v1/warehouses", {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body),
	});
export const setWarehouseActive = (id: string, active: boolean) =>
	requestJSON<Warehouse>(`v1/warehouses/${enc(id)}/${active ? "activate" : "deactivate"}`, {
		method: "POST",
	});
export const bindWarehouseNamespace = (id: string, namespace: string) =>
	requestJSON<unknown>(`v1/warehouses/${enc(id)}/namespaces`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ namespace }),
	});
