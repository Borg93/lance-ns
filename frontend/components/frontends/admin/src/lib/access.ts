import type { GrantsClient, GrantsKind } from '@rask/ui/grants-panel';
import { requestJSON } from './http';

// The /admin/access catalog seam the shared @rask/ui GrantsPanel calls (the lib never owns an API
// client — the StatusBoard precedent). Everything goes through this zone's narrow /capi access
// pass-through: session-only, owner-gated by the catalog.
const enc = encodeURIComponent;

const post = <T>(kind: GrantsKind, id: string, action: string, body?: unknown) =>
	requestJSON<T>('/capi', `v1/${kind}/${enc(id)}/access/${action}`, {
		method: 'POST',
		...(body === undefined
			? {}
			: { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
	});

export const accessClient: GrantsClient = {
	fetchAccess: (kind, id) => post(kind, id, 'list'),
	checkAccess: (kind, id, user, relation) => post(kind, id, 'check', { user, relation }),
	grantAccess: (kind, id, user, relation) => post(kind, id, 'grant', { user, relation }),
	revokeAccess: (kind, id, user, relation) => post(kind, id, 'revoke', { user, relation }),
};

/** The catalog registry (`<ns>$<table>` ids) — the picker's clickable entry points. */
export const fetchTables = () => requestJSON<{ tables: string[] }>('/capi', 'v1/table');
