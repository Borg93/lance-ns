import { expect, test, type Page } from '@playwright/test';
import { ME_ADMIN, ME_MEMBER, mockMe, signIn } from './session';

/** Open a navbar panel and hand back its viewport.
 *
 * The triggers are server-rendered, so on a loaded machine a click can land before bits-ui has
 * attached its handlers: the markup is inert rather than broken and the panel silently never
 * opens. Retrying the click rides out that race — what must hold (the panel DOES open, and carries
 * the rows asserted by the caller) is unchanged; only the delivery is made robust. It clicks only
 * while the panel is closed, so a retry can never toggle an already-open panel back shut. */
const openPanel = async (page: Page, name: string) => {
	const trigger = page
		.getByRole('navigation', { name: 'Zones' })
		.getByRole('button', { name, exact: true });
	const panel = page.locator('[data-slot="navigation-menu-viewport"]');
	await expect(async () => {
		if (!(await panel.isVisible())) await trigger.click();
		await expect(panel).toBeVisible({ timeout: 1_000 });
	}).toPass({ timeout: 20_000 });
	return panel;
};

// The admin zone's layout-level estate-admin door + the navbar IA it feeds. `/v1/me` is mocked at
// the browser boundary (the layout fetches it through this zone's /capi/v1/me pass-through):
// a bob-shaped identity (verified, NOT estate_admin) must see ForbiddenPage on EVERY admin route
// and a navbar that never exposes an admin surface; an alice-shaped one gets them.
//
// Under the three-trigger IA (8a0fbbc) this zone has no top-level entry: its surfaces are the
// Governance and Operations COLUMNS of the Lakehouse panel, appended only for an estate admin. So
// the IA half of the guarantee moved one level in — from "no Admin button in the bar" to "those
// columns do not render, and no /admin row is reachable" — and it is asserted with the panel OPEN,
// which is the only place the difference is now observable.

test.beforeEach(async ({ context }) => {
	await signIn(context); // auth-ON server: the login-first gate redirects signed-out page loads
});

test('a non-estate-admin sees ForbiddenPage on every admin route + no admin nav entries', async ({
	page,
}) => {
	await mockMe(page, ME_MEMBER);
	for (const path of [
		'/lakehouse/admin/tenants',
		'/lakehouse/admin/audit',
		'/lakehouse/admin/dlq',
	]) {
		await page.goto(path);
		await expect(page.getByText('Admin is estate-admin only')).toBeVisible();
		// The route's own content never renders behind the door.
		await expect(page.getByRole('heading', { name: 'Audit log' })).toHaveCount(0);
	}
	// The navbar hides the admin surfaces from a non-admin (fail-closed IA, not just the door).
	const nav = page.getByRole('navigation', { name: 'Zones' });
	// The bar itself is identity-independent — three domain triggers, no Admin entry in any shape…
	await expect(nav.getByRole('button', { name: 'Lakehouse', exact: true })).toBeVisible();
	await expect(nav.getByRole('button')).toHaveCount(3);
	await expect(nav.getByRole('button', { name: 'Admin', exact: true })).toHaveCount(0);
	await expect(nav.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0);
	await expect(nav.getByText('Access')).toHaveCount(0);
	// …and the real guarantee: opening the trigger that WOULD carry them shows the tighter
	// two-column panel. No Governance column, no Operations column, and not one /admin row — the
	// IA never even hints at a surface this identity is barred from.
	const panel = await openPanel(page, 'Lakehouse');
	await expect(panel.getByText('Catalog', { exact: true })).toBeVisible();
	await expect(panel.getByText('Models', { exact: true })).toBeVisible();
	await expect(panel.getByText('Governance', { exact: true })).toHaveCount(0);
	await expect(panel.getByText('Operations', { exact: true })).toHaveCount(0);
	await expect(panel.locator('a[href^="/lakehouse/admin"]')).toHaveCount(0);
});

test("an estate admin passes the door and gets Lakehouse's governance columns", async ({
	page,
}) => {
	await mockMe(page, ME_ADMIN);
	await page.route('**/api/projects*', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
	);
	await page.goto('/lakehouse/admin/tenants');
	await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible();
	const nav = page.getByRole('navigation', { name: 'Zones' });
	// Still three triggers — an admin earns panel COLUMNS, never an extra top-level entry.
	await expect(nav.getByRole('button')).toHaveCount(3);
	await expect(nav.getByRole('button', { name: 'Admin', exact: true })).toHaveCount(0);
	// Access is NOT a top-level navbar entry, in either shape…
	await expect(nav.getByRole('link', { name: 'Access', exact: true })).toHaveCount(0);
	await expect(nav.getByRole('button', { name: 'Access', exact: true })).toHaveCount(0);
	// …it is a row of Lakehouse's Governance column, which this identity DOES get. Asserted with
	// the panel open — the positive half of the non-admin guarantee above, so the two tests cannot
	// both pass on a navbar that simply renders nothing.
	const panel = await openPanel(page, 'Lakehouse');
	await expect(panel.getByText('Governance', { exact: true })).toBeVisible();
	await expect(panel.getByText('Operations', { exact: true })).toBeVisible();
	for (const href of [
		'/lakehouse/admin/access',
		'/lakehouse/admin/tenants',
		'/lakehouse/admin/audit',
		'/lakehouse/admin/events',
		'/lakehouse/admin/streams',
		'/lakehouse/admin/dlq',
	]) {
		await expect(panel.locator(`a[href="${href}"]`)).toBeVisible();
	}
	await page.keyboard.press('Escape');
	await expect(panel).toBeHidden();
	// …and it is this zone's own sidebar leaf too, which is how it is reached from inside /admin.
	await expect(
		page.locator('[data-sidebar="content"]').getByRole('link', { name: 'Access' }),
	).toBeVisible();
});

test('an unresolvable identity (catalog outage) fails CLOSED, never open', async ({ page }) => {
	await page.route('**/capi/v1/me', (route) =>
		route.fulfill({ status: 502, contentType: 'application/json', body: '{"detail":"down"}' }),
	);
	await page.goto('/lakehouse/admin/tenants');
	await expect(page.getByText('Admin is estate-admin only')).toBeVisible();
});
