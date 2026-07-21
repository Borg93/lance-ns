import * as v from 'valibot';

/**
 * Parse-don't-validate boundary for @rask/api responses. Untrusted upstream JSON is parsed ONCE here into a
 * typed, trusted value; downstream code then trusts the type. On a real schema/nullability drift this THROWS
 * — the per-route query() body lets it propagate to the route's `failed` snippet, so the UI renders a real
 * error instead of being built from values that lie about their type.
 */
export function parse<S extends v.GenericSchema>(schema: S, data: unknown): v.InferOutput<S> {
	return v.parse(schema, data);
}
