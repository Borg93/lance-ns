import { describe, expect, test } from "bun:test";
import { deriveQuality } from "./quality";
import type { Producers } from "./types";

// scope #6 — deriveQuality picks the latest run that recorded a dataQualityAssertions verdict and maps it to
// the table-page badge. Runs without a verdict are skipped; nothing recorded → null ("no quality gate").
const producers = (runs: Array<Record<string, unknown>>): Producers =>
	({ producers: runs }) as unknown as Producers;

describe("deriveQuality (#82)", () => {
	test("a passing run yields passed + the assertion count", () => {
		const q = deriveQuality(
			producers([{ quality_passed: true, quality_assertions: [{ a: 1 }, { a: 2 }] }]),
		);
		expect(q).toEqual({ passed: true, assertions: 2 });
	});

	test("a blocked run yields passed=false", () => {
		const q = deriveQuality(producers([{ quality_passed: false, quality_assertions: [{ a: 1 }] }]));
		expect(q).toEqual({ passed: false, assertions: 1 });
	});

	test("skips runs with no recorded verdict, uses the first that has one", () => {
		const q = deriveQuality(
			producers([
				{ quality_passed: null, quality_assertions: [] },
				{ quality_passed: true, quality_assertions: [] },
			]),
		);
		expect(q).toEqual({ passed: true, assertions: 0 });
	});

	test("takes the LATEST run's verdict by event_time, not the array position", () => {
		// The newest run (blocked, 07-20) is placed FIRST and an older passed run LAST — so this fails for a
		// naive last-element (or first-non-null `.find`) impl and only passes if deriveQuality actually sorts
		// by event_time. Guards the load-bearing sort that stops a stale `passed` masking the current `blocked`.
		const q = deriveQuality(
			producers([
				{
					event_time: "2026-07-20T00:00:00Z",
					quality_passed: false,
					quality_assertions: [{ a: 1 }],
				},
				{ event_time: "2026-07-01T00:00:00Z", quality_passed: true, quality_assertions: [] },
			]),
		);
		expect(q).toEqual({ passed: false, assertions: 1 });
	});

	test("no producing runs → null (honest 'no quality gate')", () => {
		expect(deriveQuality(producers([]))).toBeNull();
		expect(deriveQuality(null)).toBeNull();
		expect(
			deriveQuality({ producers: [{ quality_passed: null }] } as unknown as Producers),
		).toBeNull();
	});
});
