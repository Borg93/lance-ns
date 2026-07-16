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
