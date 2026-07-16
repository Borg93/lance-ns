import { env } from "$env/dynamic/private";
import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";

// Embedded experiment tracking (#53) — the same-origin BFF for the deployed Perses "Model Training —
// experiment metrics" dashboard. It runs that dashboard's exact PromQL queries against GreptimeDB's
// Prometheus-compatible endpoint server-side and returns per-model series, so the /experiments page
// renders the real training metrics (OTLP → GreptimeDB, #18 — not MLflow) without ever exposing a
// credential to the browser: GreptimeDB is reached over its in-cluster ClusterIP, so the §5e edge
// auth (nginx auth_basic on the gateway's /greptime/ and /perses/ locations) is not in this path.
//
// Session-gated on a governed stack (mirroring the /capi catalog stance): model identity is FGA-gated
// everywhere else, so an anonymous front-door caller must not read the estate's model names + training
// activity straight off the metric store. Without OIDC configured (auth-off dev) it answers openly.
// Read-only and metrics-only — no user data, no write surface; when GREPTIME_API is unset it 501s.
const GREPTIME_API = env.GREPTIME_API ?? "";

// The three panels of the deployed Perses `training` dashboard (chart/templates/perses-dashboards.yaml),
// query-for-query. Kept here as the single source so the page renders exactly what Perses shows.
const PANELS = [
	{
		key: "runs",
		title: "Training runs /s by model",
		query: "sum by (lance_model) (rate(lance_training_runs_total[5m]))",
	},
	{
		key: "rows",
		title: "Rows seen (latest run) by model",
		query: "max by (lance_model) (lance_training_rows_seen)",
	},
	{
		key: "features",
		title: "Feature datasets used (latest run) by model",
		query: "max by (lance_model) (lance_training_features)",
	},
] as const;

type Series = { model: string; value: number };

async function promql(base: string, fetchFn: typeof fetch, query: string): Promise<Series[]> {
	const url = `${base}/v1/prometheus/api/v1/query?query=${encodeURIComponent(query)}`;
	const res = await fetchFn(url);
	if (!res.ok) throw new Error(`greptime ${res.status}`);
	const body = (await res.json()) as {
		data?: { result?: { metric?: Record<string, string>; value?: [number, string] }[] };
	};
	return (body.data?.result ?? [])
		.map((r) => ({ model: r.metric?.lance_model ?? "?", value: Number(r.value?.[1] ?? "0") }))
		.filter((s) => Number.isFinite(s.value))
		.sort((a, b) => a.model.localeCompare(b.model));
}

export const GET: RequestHandler = async ({ fetch, locals }) => {
	if (locals.authEnabled && !locals.session) {
		return json({ detail: "sign in to view experiment metrics" }, { status: 401 });
	}
	if (!GREPTIME_API) {
		return json(
			{ detail: "experiment tracking requires the observability stack (GreptimeDB)" },
			{ status: 501 },
		);
	}
	try {
		const panels = await Promise.all(
			PANELS.map(async (p) => ({
				key: p.key,
				title: p.title,
				series: await promql(GREPTIME_API, fetch, p.query),
			})),
		);
		return json({
			dashboard: "Model Training — experiment metrics",
			source: "GreptimeDB (OTLP)",
			panels,
		});
	} catch (err) {
		console.error(`experiments proxy upstream failure: ${String(err)}`);
		return json({ detail: String(err) }, { status: 502 });
	}
};
