import { test, expect, type Route } from '@playwright/test';
import { mockMe, signIn } from './session';

// Hermetic /dlq coverage (#83): the ops panel reads the transactional-outbox backlog via /api/admin/dlq and
// replays one event through the session-only /api/admin/dlq/{run}/replay BFF. Mock both; assert the events
// render, a replay POSTs + refreshes (the drained event leaves the list), poison is unreplayable, and the
// nav exposes the route.

const json = (route: Route, body: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

const replayed = new Set<string>();

function backlog() {
	const events = [
		{
			run_id: 'run-1',
			event_type: 'COMPLETE',
			job: 'ingest',
			outputs: ['bronze$a'],
			inputs: [],
			parseable: true,
		},
		{ run_id: 'bad-1', event_type: null, job: null, outputs: [], inputs: [], parseable: false },
	].filter((e) => !replayed.has(e.run_id));
	return { depth: events.length, oldest_age_seconds: 42, events, limit: 200 };
}

test.beforeEach(async ({ context, page }) => {
	await signIn(context); // auth-ON server: the login-first gate redirects signed-out page loads
	await mockMe(page); // estate-admin identity: the admin layout door opens
	replayed.clear();
	await page.route('**/api/admin/dlq/*/replay', (route) => {
		const m = route
			.request()
			.url()
			.match(/\/admin\/dlq\/([^/]+)\/replay/);
		if (m) replayed.add(decodeURIComponent(m[1]));
		return json(route, { status: 'replayed', run_id: m ? decodeURIComponent(m[1]) : '' });
	});
	await page.route('**/api/admin/dlq?**', (route) => json(route, backlog()));
});

test('renders the outbox at-risk events with a depth badge', async ({ page }) => {
	await page.goto('/admin/dlq');
	await expect(page.getByRole('heading', { name: 'Lineage DLQ' })).toBeVisible();
	const table = page.locator('table');
	await expect(table).toContainText('run-1');
	await expect(table).toContainText('bronze$a');
	await expect(table).toContainText('poison'); // the unparseable object is surfaced
	await expect(page.locator('.depth')).toContainText('depth 2');
});

test('replay POSTs to the BFF and the drained event leaves the list', async ({ page }) => {
	await page.goto('/admin/dlq');
	await expect(page.locator('table')).toContainText('run-1');
	await page.getByRole('button', { name: 'Replay run-1' }).click();
	await expect(page.locator('.msg')).toContainText('Replayed run-1');
	// the reload drops the drained event; only the poison row remains
	await expect(page.locator('table')).not.toContainText('run-1');
	await expect(page.locator('table')).toContainText('poison');
});

test('a poison object is not replayable', async ({ page }) => {
	await page.goto('/admin/dlq');
	const poisonRow = page.locator('tr.poison');
	await expect(poisonRow).toContainText('unreplayable');
	await expect(poisonRow.getByRole('button', { name: /Replay/ })).toHaveCount(0);
});

test('shows the honest empty state when the outbox is drained', async ({ page }) => {
	replayed.add('run-1');
	replayed.add('bad-1');
	await page.goto('/admin/dlq');
	await expect(page.getByText('The outbox is empty')).toBeVisible();
});

test('the shared sidebar marks the DLQ leaf active', async ({ page }) => {
	await page.goto('/admin/dlq');
	await expect(page.locator('[data-active="true"]').filter({ hasText: 'DLQ' })).toBeVisible();
});
