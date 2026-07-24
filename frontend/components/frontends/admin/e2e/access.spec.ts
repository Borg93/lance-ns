import { expect, test } from '@playwright/test';
import { mockMe, signIn } from './session';

// `/admin/access` — the estate access surface: registry entry points, the #51 review through the
// zone's narrow kinded pass-through, and the #68 check playground. Hermetic via page.route.

const ACL = {
	object: 'table:db1$t',
	grants: [{ relation: 'can_read_data', users: ['user:alice'] }],
};

let checkPost: { user: string; relation: string } | null;

test.beforeEach(async ({ context, page }) => {
	await signIn(context);
	await mockMe(page); // estate-admin identity: the admin layout door opens
	checkPost = null;
	await page.route('**/admin/capi/**', (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^.*\/capi/, '');
		// The layout's identity fetch shares this glob and this handler REGISTERED LAST wins —
		// fall back to the mockMe route instead of 404ing the door shut.
		if (path === '/v1/me') return route.fallback();
		if (path === '/v1/table')
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ tables: ['db1$t'] }),
			});
		if (path === '/v1/table/db1%24t/access/list' || path === '/v1/table/db1$t/access/list')
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(ACL),
			});
		if (path.endsWith('/access/check')) {
			checkPost = req.postDataJSON() as { user: string; relation: string };
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ user: checkPost.user, relation: checkPost.relation, allowed: true }),
			});
		}
		return route.fulfill({
			status: 404,
			contentType: 'application/json',
			body: '{"detail":"unstubbed"}',
		});
	});
});

test('registry entries open the review panel and the check playground posts through the kinded route', async ({
	page,
}) => {
	await page.goto('/admin/access');
	// The registry offers the table (and its derived namespace) as one-click entries.
	await page.getByRole('button', { name: 'db1$t', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'table:db1$t' })).toBeVisible();
	await page.getByRole('button', { name: 'Access review' }).click();
	await expect(page.locator('table.acl')).toContainText('can_read_data');
	// The #68 simulator: probe a (user, relation) — the wire body is the contract.
	await page.getByPlaceholder('user (e.g. alice), or role:… / team:…#member').first().fill('bob');
	// The simulator's action picker is the @rask/ui Select (bits-ui) — open by aria-label, pick option.
	await page.getByLabel('Simulate action').click();
	await page.getByRole('option', { name: 'can_read_data', exact: true }).click();
	await page.getByRole('button', { name: 'Check', exact: true }).click();
	await expect.poll(() => checkPost).toEqual({ user: 'bob', relation: 'can_read_data' });
});

test('a manual namespace target loads the kind-generalized panel', async ({ page }) => {
	await page.route('**/admin/capi/v1/namespace/gold/access/list', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				object: 'namespace:gold',
				grants: [{ relation: 'can_delete', users: ['user:alice'] }],
			}),
		}),
	);
	await page.goto('/admin/access');
	await page.getByLabel('Object kind').click();
	await page.getByRole('option', { name: 'namespace', exact: true }).click();
	await page.getByLabel('Object id').fill('gold');
	await page.getByRole('button', { name: 'Load', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'namespace:gold' })).toBeVisible();
	await page.getByRole('button', { name: 'Access review' }).click();
	await expect(page.locator('table.acl')).toContainText('can_delete');
});
