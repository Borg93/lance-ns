import { expect, test } from '@playwright/test';
import { ME_ADMIN, ME_MEMBER, mockMe, signIn } from './session';

// The admin zone's layout-level estate-admin door + the navbar IA it feeds. `/v1/me` is mocked at
// the browser boundary (the layout fetches it through this zone's /capi/v1/me pass-through):
// a bob-shaped identity (verified, NOT estate_admin) must see ForbiddenPage on EVERY admin route
// and a navbar WITHOUT the Admin/Access entries; an alice-shaped one gets the full entry set.

test.beforeEach(async ({ context }) => {
	await signIn(context); // auth-ON server: the login-first gate redirects signed-out page loads
});

test('a non-estate-admin sees ForbiddenPage on every admin route + no admin nav entries', async ({
	page,
}) => {
	await mockMe(page, ME_MEMBER);
	for (const path of ['/admin/tenants', '/admin/audit', '/admin/dlq']) {
		await page.goto(path);
		await expect(page.getByText('Admin is estate-admin only')).toBeVisible();
		// The route's own content never renders behind the door.
		await expect(page.getByRole('heading', { name: 'Audit log' })).toHaveCount(0);
	}
	// The navbar hides the admin surfaces from a non-admin (fail-closed IA, not just the door).
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Data' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0);
	await expect(nav.getByRole('link', { name: 'Access' })).toHaveCount(0);
});

test('an estate admin passes the door and gets the Admin + Access navbar entries', async ({
	page,
}) => {
	await mockMe(page, ME_ADMIN);
	await page.route('**/admin/api/projects*', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.goto('/admin/tenants');
	await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible();
	const nav = page.getByRole('navigation', { name: 'Zones' });
	await expect(nav.getByRole('link', { name: 'Admin' })).toBeVisible();
	await expect(nav.getByRole('link', { name: 'Access' })).toBeVisible();
});

test('an unresolvable identity (catalog outage) fails CLOSED, never open', async ({ page }) => {
	await page.route('**/capi/v1/me', (route) =>
		route.fulfill({ status: 502, contentType: 'application/json', body: '{"detail":"down"}' }),
	);
	await page.goto('/admin/tenants');
	await expect(page.getByText('Admin is estate-admin only')).toBeVisible();
});
