import { test, expect, type Route } from '@playwright/test';

// Hermetic /streams coverage: the panel reads the trimmed JetStream overview via the /api/jetstream BFF.
// Mock it; assert the stream cards + consumer lag rows render (DLQ flagged, redelivery highlighted) and
// that a 403 renders the forbidden state.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

// Trimmed form of the REAL live /jsz sample (kind cluster, 2026-07-23): LINEAGE with its durable push
// consumer, plus the DLQ stream carrying an ephemeral consumer with backlog + redeliveries.
const OVERVIEW = {
	now: '2026-07-23T19:02:29.893843405Z',
	totals: { streams: 2, consumers: 3, messages: 141, bytes: 365657 },
	streams: [
		{
			name: 'DLQ',
			subjects: ['dlq.lineage.>'],
			retention: 'limits',
			storage: 'file',
			max_age_ns: 0,
			max_msgs: -1,
			max_bytes: -1,
			num_replicas: 1,
			state: { messages: 5, bytes: 2000, first_seq: 1, last_seq: 5, consumer_count: 1 },
			consumers: [
				{
					name: 'fR9hEVt8',
					durable: false,
					num_pending: 4,
					num_ack_pending: 1,
					num_redelivered: 2,
					last_active: '2026-07-23T16:19:33.986839443Z',
				},
			],
		},
		{
			name: 'LINEAGE',
			subjects: ['lineage.events.>'],
			retention: 'limits',
			storage: 'file',
			max_age_ns: 604800000000000,
			max_msgs: -1,
			max_bytes: -1,
			num_replicas: 1,
			state: { messages: 136, bytes: 363657, first_seq: 10496, last_seq: 10631, consumer_count: 2 },
			consumers: [
				{
					name: 'lance-ray-durable',
					durable: true,
					deliver_group: 'lance-ray',
					num_pending: 0,
					num_ack_pending: 0,
					num_redelivered: 0,
					last_active: '2026-07-23T16:19:33.986839443Z',
				},
			],
		},
	],
};

test('renders stream cards with consumer lag rows', async ({ page }) => {
	await page.route('**/admin/api/jetstream*', (route) => json(route, OVERVIEW));
	await page.goto('/admin/streams');
	await expect(page.getByRole('heading', { name: 'Streams' })).toBeVisible();

	// Stream cards with their config + state.
	const lineage = page.getByLabel('Stream LINEAGE');
	await expect(lineage).toContainText('lineage.events.>');
	await expect(lineage).toContainText('136 msgs');
	await expect(lineage).toContainText('limits');
	// Consumer lag rows: the durable push consumer with its deliver group.
	await expect(lineage.locator('table')).toContainText('lance-ray-durable');
	await expect(lineage.locator('table')).toContainText('lance-ray');

	// The DLQ stream is visually flagged, and its ephemeral consumer shows backlog + redeliveries.
	const dlq = page.getByLabel('Stream DLQ');
	await expect(dlq).toContainText('DLQ');
	await expect(dlq.locator('.badge.dlqbadge')).toBeVisible();
	await expect(dlq.locator('table')).toContainText('fR9hEVt8 (ephemeral)');
	await expect(dlq.locator('td.warn')).toHaveText('2'); // redelivered > 0 highlighted
});

test('a 403 from the BFF renders the forbidden state', async ({ page }) => {
	await page.route('**/admin/api/jetstream*', (route) =>
		json(route, { detail: 'the stream view is admin-only (project admin required)' }, 403),
	);
	await page.goto('/admin/streams');
	await expect(page.getByText('The stream view is admin-only')).toBeVisible();
	await expect(page.locator('table')).toHaveCount(0);
});

test('Refresh re-queries the BFF', async ({ page }) => {
	let calls = 0;
	await page.route('**/admin/api/jetstream*', (route) => {
		calls += 1;
		return json(route, OVERVIEW);
	});
	await page.goto('/admin/streams');
	await expect(page.getByLabel('Stream LINEAGE')).toBeVisible();
	const before = calls;
	await page.getByRole('button', { name: 'Refresh' }).click();
	await expect.poll(() => calls).toBeGreaterThan(before);
});
