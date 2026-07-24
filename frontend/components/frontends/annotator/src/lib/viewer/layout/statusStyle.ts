/** Shared status → semantic style map for the sidebar/list. Kept tiny + in one
 *  place so the badge/dot look identical everywhere. */
export function statusDot(status: string): string {
	switch (status) {
		case 'accepted':
			return 'bg-emerald-500';
		case 'rejected':
			return 'bg-rose-500';
		case 'prediction':
			return 'bg-amber-500';
		case 'reviewed':
			return 'bg-sky-500';
		default:
			return 'bg-muted-foreground';
	}
}

export function statusBadge(status: string): string {
	switch (status) {
		case 'accepted':
			return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400';
		case 'rejected':
			return 'bg-rose-500/15 text-rose-600 dark:text-rose-400';
		case 'prediction':
			return 'bg-amber-500/15 text-amber-600 dark:text-amber-400';
		case 'reviewed':
			return 'bg-sky-500/15 text-sky-600 dark:text-sky-400';
		default:
			return 'bg-muted text-muted-foreground';
	}
}
