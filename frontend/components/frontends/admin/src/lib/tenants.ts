import * as v from 'valibot';

// Wire contract for the catalog's first-class projects API (endpoints/projects.py): a BARE ARRAY of
// project summaries — parsed, not cast, at the browser boundary (the @rask/api parse-don't-validate rule).

export const ProjectWarehouseSchema = v.object({
	id: v.string(),
	bucket: v.string(),
	status: v.string(),
});

export const ProjectSchema = v.object({
	project: v.string(),
	warehouses: v.array(ProjectWarehouseSchema),
	admins: v.array(v.string()),
});
export type Project = v.InferOutput<typeof ProjectSchema>;

export const ProjectsResponseSchema = v.array(ProjectSchema);
