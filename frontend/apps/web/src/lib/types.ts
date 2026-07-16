// Frontend types are DERIVED from the backend OpenAPI contract — never hand-mirror the Pydantic models
// (that silently drifts). `api.generated.ts` is generated from `openapi.json` (itself produced from the
// FastAPI app); regenerate both with `bun run gen:types`. Only domain constants live here by hand.
import type { components } from "./api.generated";

type S = components["schemas"];

export type DatasetGovernance = S["DatasetGovernance"];
export type GraphNode = S["GraphNode"];
export type GraphEdge = S["GraphEdge"];
export type LineageGraph = S["LineageGraph"];
export type ProducerInfo = S["ProducerInfo"];
export type Producers = S["Producers"];
export type EventRecord = S["EventRecord"];
export type SearchResults = S["SearchResults"];
export type Events = S["Events"];
export type DemoDataset = S["DemoDataset"];
export type DemoDatasets = S["DemoDatasets"];
export type RunStatus = S["RunStatus"];
export type Runs = S["Runs"];
export type ColumnRef = S["ColumnRef"];
export type ColumnEdge = S["ColumnEdge"];
export type ColumnGraph = S["ColumnGraph"];
export type ColumnNeighbors = S["ColumnNeighbors"];
export type DatasetSummary = S["DatasetSummary"];
export type Datasets = S["Datasets"];
export type JobSummary = S["JobSummary"];
export type Jobs = S["Jobs"];
export type Namespaces = S["Namespaces"];

// The medallion datasets, in flow order (raw -> bronze -> silver -> gold). Domain knowledge, not schema.
export const KNOWN = ["raw_events", "bronze$events", "silver$features", "gold$catalog"] as const;
export const LAYER: Record<string, number> = {
	raw_events: 0,
	bronze$events: 1,
	silver$features: 2,
	gold$catalog: 3,
};
