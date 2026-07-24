import { expect, test } from '@playwright/test';
import { mockMe, signIn } from './session';

// The tenants panel (goal cond 6, rebuilt on the shared DataTable — goal cond 4): one row per
// warehouse with its owning project + effective admins, rendered from the catalog's first-class
// projects API through the bearer-forwarding BFF. Hermetic: the BFF route is same-origin, so
// page.route mocks it.

test.beforeEach(async ({ context, page }) => {
	await signIn(context); // auth-ON server: the login-first gate redirects signed-out page loads
	await mockMe(page); // estate-admin identity: the admin layout door opens
});

const FIXTURE = [
	{
		project: 'acme',
		warehouses: [
			{ id: 'acme-wh', bucket: 'acme-bucket', status: 'active' },
			{ id: 'acme-cold', bucket: 'acme-archive', status: 'deactivated' },
		],
		admins: ['alice', 'bob'],
	},
	{
		project: 'beta',
		warehouses: [{ id: 'beta-wh', bucket: 'beta-bucket', status: 'active' }],
		admins: [],
	},
];

test('renders one sortable row per warehouse with project, status, and admins', async ({
	page,
}) => {
	await page.route('**/admin/api/projects*', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FIXTURE) }),
	);
	await page.goto('/admin/tenants');
	// acme spans two warehouse rows; the deactivated one carries the warn-toned status.
	const cold = page.locator('tr', { hasText: 'acme-cold' });
	await expect(cold).toContainText('deactivated');
	await expect(cold).toContainText('acme-archive');
	await expect(cold.locator('.chip')).toHaveCount(2); // alice + bob
	// FGA-degraded admins render honestly, not as an error.
	await expect(page.locator('tr', { hasText: 'beta-wh' })).toContainText('none listed');
	// the text search narrows the rows
	await page.getByPlaceholder('Search tenants…').fill('beta');
	await expect(page.locator('tr', { hasText: 'acme-wh' })).toHaveCount(0);
	await expect(page.locator('tr', { hasText: 'beta-wh' })).toBeVisible();
});

test('a non-estate-admin sees the forbidden state', async ({ page }) => {
	await page.route('**/admin/api/projects*', (route) =>
		route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"forbidden"}' }),
	);
	await page.goto('/admin/tenants');
	await expect(page.getByText('Tenant enumeration is estate-admin only.')).toBeVisible();
});
