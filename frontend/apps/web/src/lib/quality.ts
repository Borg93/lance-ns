import type { Producers } from "./types";

// scope #6 quality gate. The validator records its dataQualityAssertions verdict on the run that produced a
// dataset (medallion stages do; a plain catalog table has none). `quality_passed=false` means the gate ran
// and blocked. We surface the latest run that recorded a verdict — null means no run has one, stated honestly.
export type QualityBadge = { passed: boolean; assertions: number } | null;

export function deriveQuality(producers: Producers | null | undefined): QualityBadge {
	const run = producers?.producers?.find((p) => p.quality_passed != null);
	if (!run || run.quality_passed == null) return null;
	return { passed: run.quality_passed, assertions: run.quality_assertions?.length ?? 0 };
}
