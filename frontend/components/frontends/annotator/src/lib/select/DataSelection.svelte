<script lang="ts">
	// The landing/selection view — replaces the old hardcoded demo unit. Datasets come
	// from the viewer BFF (/api/datasets); picking one loads its descriptor (the same
	// schema-agnostic DatasetView the media zone renders from), then a paged documents
	// grid with thumbnails, then a per-document chunk picker that opens the annotate
	// canvas via `?keys=` (the existing deep-link contract — the read plane's bridge).
	import { onMount } from 'svelte';
	import {
		getDatasetView,
		getHealth,
		listDatasets,
		listDocuments,
		type Document,
		type DocumentsResponse,
	} from '@lance/api';
	import { setActiveView, type DatasetView } from '@lance/api/descriptor';
	import { Button, Select } from '@lance/ui';
	import DocTile from './DocTile.svelte';
	import ChunkPicker from './ChunkPicker.svelte';

	let { onopen }: { onopen: (keys: string[]) => void } = $props();

	interface DatasetEntry {
		id: string;
		docs: number | null;
	}

	const PER_PAGE = 24;

	let datasets = $state<DatasetEntry[]>([]);
	let view = $state<DatasetView | null>(null);
	let error = $state<string | null>(null);
	let docsPage = $state<DocumentsResponse | null>(null);
	let loadingDocs = $state(false);
	let openDoc = $state<Document | null>(null);

	const totalPages = $derived(docsPage ? Math.max(1, Math.ceil(docsPage.total / PER_PAGE)) : 1);

	async function loadDocs(page: number): Promise<void> {
		loadingDocs = true;
		try {
			docsPage = await listDocuments(page, PER_PAGE);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingDocs = false;
		}
	}

	async function selectDataset(id: string, defaultId: string | null): Promise<void> {
		error = null;
		openDoc = null;
		docsPage = null;
		try {
			const next = await getDatasetView(id, id === defaultId);
			setActiveView(next); // the module-level singleton the URL helpers read
			view = next;
			datasetChoice = id;
			await loadDocs(1);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	let defaultId = $state<string | null>(null);

	// The dataset picker binds here (bits-ui Select is bind-only); a change loads
	// the picked dataset. Guarded so programmatic sync never re-loads the same one.
	let datasetChoice = $state('');
	$effect(() => {
		if (datasetChoice && datasetChoice !== view?.id) {
			void selectDataset(datasetChoice, defaultId);
		}
	});

	onMount(async () => {
		try {
			// The default dataset id derives from the health endpoint's db path (the same
			// convention as the media zone's descriptor store) so its URLs skip `?dataset=`.
			const [ds, health] = await Promise.all([listDatasets(), getHealth().catch(() => null)]);
			datasets = ds.map((d) => ({
				id: d.id,
				docs: d.tables?.['documents']?.row_count ?? null,
			}));
			defaultId =
				health?.db.path
					.replace(/\.lance$/, '')
					.split('/')
					.pop() ?? null;
			const first = ds.find((d) => d.id === defaultId) ?? ds[0];
			if (first) await selectDataset(first.id, defaultId);
			else error = 'No datasets available from the viewer service.';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});
</script>

<div class="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4" data-testid="data-selection">
	{#if openDoc && view}
		<ChunkPicker {view} doc={openDoc} {onopen} onback={() => (openDoc = null)} />
	{:else}
		<div class="flex shrink-0 flex-wrap items-center gap-3">
			<div>
				<h1 class="text-base font-semibold">Annotate</h1>
				<p class="text-muted-foreground text-xs">
					Pick a document, then a chunk — or review a whole document.
				</p>
			</div>
			{#if datasets.length > 1 && view}
				<div class="ml-auto w-56">
					<Select
						options={datasets.map((d) => ({
							value: d.id,
							label: d.docs != null ? `${d.id} (${d.docs} docs)` : d.id,
						}))}
						bind:value={datasetChoice}
						ariaLabel="Dataset"
					/>
				</div>
			{:else if view}
				<span class="text-muted-foreground ml-auto font-mono text-xs" data-testid="dataset-id">
					{view.id}
				</span>
			{/if}
		</div>

		{#if error}
			<p class="text-destructive text-sm" data-testid="selection-error">{error}</p>
		{:else if docsPage === null}
			<p class="text-muted-foreground text-sm">Loading datasets…</p>
		{:else}
			<div
				class="grid min-h-0 flex-1 auto-rows-min grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-3 overflow-y-auto pr-1"
			>
				{#each docsPage.docs as doc (view!.docId(doc))}
					<DocTile view={view!} {doc} onclick={() => (openDoc = doc)} />
				{/each}
			</div>
			<div class="flex shrink-0 items-center justify-center gap-2">
				<Button
					variant="outline"
					size="sm"
					disabled={loadingDocs || docsPage.page <= 1}
					onclick={() => void loadDocs(docsPage!.page - 1)}
				>
					Previous
				</Button>
				<span class="text-muted-foreground text-xs tabular-nums">
					page {docsPage.page} / {totalPages} · {docsPage.total} documents
				</span>
				<Button
					variant="outline"
					size="sm"
					disabled={loadingDocs || docsPage.page >= totalPages}
					onclick={() => void loadDocs(docsPage!.page + 1)}
				>
					Next
				</Button>
			</div>
		{/if}
	{/if}
</div>
