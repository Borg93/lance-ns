import { createLineageClient } from '@repo/api/lineage';
import { bff } from './http';

// This zone's binding of the shared lineage-plane client (@repo/api/lineage), which was three
// near-identical copies before. Spread into named module exports so call sites keep importing
// `$lib/api` unchanged.
export const {
	fetchGraph,
	fetchEstateGraph,
	fetchProducers,
	fetchReaders,
	fetchEvents,
	fetchDlq,
	replayDlq,
	fetchDemo,
	fetchRuns,
	fetchRunInputs,
	fetchDatasets,
	fetchUpstream,
	fetchDownstream,
	fetchSearch,
	fetchJobs,
	fetchNamespaces,
	fetchColumnGraph,
	fetchCreator,
	fetchSchema,
	fetchColumnUpstream,
	fetchColumnDownstream,
	fetchGovernance,
	addDatasetTag,
	removeDatasetTag,
	setDatasetDescription,
	listDatasets,
	listJobs,
	listRuns,
} = createLineageClient(bff);
