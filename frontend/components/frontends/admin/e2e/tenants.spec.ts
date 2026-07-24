import { expect, test } from '@playwright/test';
import { mockMe, signIn } from './session';

// The tenants panel (goal cond 6): renders the catalog's first-class projects API through the
// bearer-forwarding BFF. Hermetic: the BFF route is same-origin, so page.route mocks it.

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

test('renders tenants with warehouses, statuses, and admins', async ({ page }) => {
	await page.route('**/admin/api/projects*', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FIXTURE) }),
	);
	await page.goto('/admin/tenants');
	await expect(page.locator('section.tenant', { hasText: 'acme' })).toContainText('2 warehouses');
	await expect(page.locator('section.tenant', { hasText: 'acme' })).toContainText('deactivated');
	await expect(page.locator('section.tenant', { hasText: 'acme' }).locator('.chip')).toHaveCount(2);
	// FGA-degraded admins render honestly, not as an error.
	await expect(page.locator('section.tenant', { hasText: 'beta' })).toContainText('none listed');
});

test('a non-estate-admin sees the forbidden state', async ({ page }) => {
	await page.route('**/admin/api/projects*', (route) =>
		route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"forbidden"}' }),
	);
	await page.goto('/admin/tenants');
	await expect(page.getByText('Tenant enumeration is estate-admin only.')).toBeVisible();
});
