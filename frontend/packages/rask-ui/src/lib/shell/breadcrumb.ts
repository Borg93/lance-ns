/**
 * Breadcrumb + project derivation for the shared shell — the single source of
 * truth so `app-shell`, `project-switcher`, and any future chrome can't drift.
 *
 * Project-first IA via HOST: the project IS the request host (e.g. demo.localhost),
 * so the pathname carries only the domain + in-domain trail. Every path segment is
 * a crumb (the DOMAIN is the first crumb); the project is the breadcrumb ROOT and is
 * derived from the host, never from the path.
 */

export type Crumb = {
	id: string;
	label: string;
	/** The absolute, domain-relative path this crumb points at (`/data/tables`). */
	href: string;
};

/** Percent-decode a path segment for display, falling back to the raw text on a malformed
 *  escape (`decodeURIComponent` throws on a lone `%`). Ids like `silver$features` reach the
 *  URL encoded (`silver%24features`), and the raw form is unreadable in a breadcrumb. */
function humanise(seg: string): string {
	let decoded = seg;
	try {
		decoded = decodeURIComponent(seg);
	} catch {
		// keep the raw segment
	}
	return decoded.replace(/-/g, ' ');
}

/**
 * Crumbs for a domain-relative pathname, in order. Each segment becomes one crumb
 * keyed by its accumulated path prefix (so repeated segments like `/studio/studio`
 * stay unique) and carrying the `href` of that prefix, so the trail is navigable —
 * every crumb but the last links back up its own path. The human label drops dashes
 * and percent-decodes. The domain (first segment) is kept — it is the first crumb,
 * not the project.
 */
export function pathCrumbs(pathname: string): Crumb[] {
	const segs = pathname.split('/').filter(Boolean);
	return segs.map((seg, i) => {
		const id = segs.slice(0, i + 1).join('/');
		return { id, label: humanise(seg), href: `/${id}` };
	});
}

/**
 * The project label carried by a request host (e.g. `demo.localhost` -> `demo`),
 * or `null` when the host has none. Only a real subdomain is a project label: bare
 * hosts (`localhost`) and IPv4 hosts (`127.0.0.1` — a numeric first label is an
 * octet) have no project.
 */
export function projectFromHost(host: string): string | null {
	const labels = host.split('.');
	if (labels.length > 1 && !/^\d+$/.test(labels[0] ?? '')) {
		return labels[0] || null;
	}
	return null;
}
