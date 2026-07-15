// Typed client for the CATALOG service via the /capi BFF proxy (the /api proxy covers lineage).
// Types are generated from docs/catalog-openapi.json (`bun run gen:types:catalog`) — never hand-mirrored.
// The describe route serializes with response_model_exclude_none, so its null fields arrive absent —
// read optional fields with `?? null` rather than trusting the generated required-nullable shape.
import type { components } from "./catalog.generated";
import { FETCH_TIMEOUT_MS, timeoutSignal } from "./http";

export type ModelSummary = components["schemas"]["ModelSummary"];
export type ModelsList = components["schemas"]["ModelsListResponse"];
export type ModelDescribe = components["schemas"]["ModelDescribeResponse"];
export type PromoteResponse = components["schemas"]["PromoteResponse"];

/** A fetch outcome that keeps the status: the models page needs 401 ("sign in") ≠ 502 ("offline"). */
export type CatalogResult<T> =
	| { ok: true; data: T }
	| { ok: false; status: number; detail: string };

async function requestJSON<T>(path: string, init?: RequestInit): Promise<CatalogResult<T>> {
	try {
		const res = await fetch(`/capi/${path}`, { ...init, signal: timeoutSignal(FETCH_TIMEOUT_MS) });
		const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
		if (!res.ok) {
			const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
			return { ok: false, status: res.status, detail };
		}
		return { ok: true, data: body as T };
	} catch (err) {
		return { ok: false, status: 0, detail: String(err) };
	}
}

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
