import { redirect } from "@sveltejs/kit";

// The lineage graph (apps/web's old home) moved to the lineage micro-frontend zone. Until apps/web is
// retired (P5), send its root to the remaining governance landing.
export const load = () => {
	redirect(307, "/audit");
};
