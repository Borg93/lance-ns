import * as v from 'valibot';

// The control-plane change-event wire contract. Mirrors services/common/control_events.py::CatalogControlEvent
// and services/catalog/api/v1/endpoints/events.py::EventsResponse — parsed (not cast) at the BFF boundary so
// a drift from the backend throws here rather than lying downstream (the @rask/api parse-don't-validate rule).

export const ControlEventSchema = v.object({
	event_id: v.string(),
	occurred_at: v.string(), // ISO-8601 UTC
	action: v.string(),
	object_type: v.string(),
	object_id: v.string(),
	actor: v.nullable(v.string()),
	extra: v.record(v.string(), v.unknown()),
});
export type ControlEvent = v.InferOutput<typeof ControlEventSchema>;

export const EventsPageSchema = v.object({
	events: v.array(ControlEventSchema),
	cursor: v.number(),
	reset: v.boolean(),
});
export type EventsPage = v.InferOutput<typeof EventsPageSchema>;
