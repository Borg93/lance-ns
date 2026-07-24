import { describe, expect, it } from "vitest";
import { pickCorners } from "./MagneticTool";

/** A cols×rows response map with the given peaks (everything else 0). */
function map(cols: number, rows: number, peaks: [number, number, number][]): Float32Array {
  const m = new Float32Array(cols * rows);
  for (const [x, y, v] of peaks) m[y * cols + x] = v;
  return m;
}

describe("pickCorners (Shi–Tomasi picking over a min-eigenvalue map)", () => {
  it("keeps local maxima above the quality threshold", () => {
    const m = map(20, 20, [
      [5, 5, 1.0],
      [15, 15, 0.5],
      [10, 10, 0.0005], // below quality × max (0.001 × 1.0)
    ]);
    const pts = pickCorners(m, 20, 20, 0.001, 3);
    expect(pts).toContainEqual([5, 5]);
    expect(pts).toContainEqual([15, 15]);
    expect(pts).not.toContainEqual([10, 10]);
  });

  it("suppresses the weaker of two corners closer than minDist (strongest wins)", () => {
    const m = map(20, 20, [
      [5, 5, 1.0],
      [7, 5, 0.9], // 2px away < minDist 3
    ]);
    const pts = pickCorners(m, 20, 20, 0.001, 3);
    expect(pts).toContainEqual([5, 5]);
    expect(pts).not.toContainEqual([7, 5]);
  });

  it("keeps corners exactly at/beyond minDist", () => {
    const m = map(20, 20, [
      [5, 5, 1.0],
      [9, 5, 0.9], // 4px away ≥ minDist 3
    ]);
    const pts = pickCorners(m, 20, 20, 0.001, 3);
    expect(pts).toHaveLength(2);
  });

  it("returns [] for a flat (zero) response map", () => {
    expect(pickCorners(new Float32Array(400), 20, 20, 0.001, 3)).toEqual([]);
  });
});
