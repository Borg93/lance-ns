import type { LayoutServerLoad } from './$types';
import { zoneLayoutLoad } from '@repo/api/bff';

// The estate-wide zone layout contract (identity + auth-enabled flag for the shared TopNavbar),
// single-sourced in @repo/api/bff so every zone derives the SAME user.
export const load: LayoutServerLoad = zoneLayoutLoad;
