import { Graphics } from 'pixi.js';
import Flatbush from 'flatbush';
import { boundsFromPolygon, snapToPoint } from '../interaction/geometry.js';
import { loadOpenCV } from './opencv.js';
import {
	type CommitShape,
	HANDLE_FILL,
	type InteractionContext,
	SNAP_THRESHOLD_PX,
	STROKE_COLOR,
	type Tool,
} from '../interaction/types.js';

/**
 * Shi–Tomasi corner picking over a min-eigenvalue response map: keep local maxima
 * above `quality × max(response)`, suppressing neighbors within `minDist` via a
 * coarse occupancy grid. Replaces `goodFeaturesToTrack` (absent from the opencv-js
 * build) with the same underlying selection rule. Border rows/cols are excluded from
 * candidacy (the 3×3 max test needs a full neighborhood) — same practical effect as
 * goodFeaturesToTrack's aperture border; snapping falls to the nearest interior corner.
 */
export function pickCorners(
	response: Float32Array,
	cols: number,
	rows: number,
	quality: number,
	minDist: number,
): [number, number][] {
	let max = 0;
	for (let i = 0; i < response.length; i++) if (response[i] > max) max = response[i];
	const threshold = max * quality;
	if (threshold <= 0) return [];

	// Candidates = 3×3 local maxima above the quality threshold, strongest first.
	const candidates: [number, number, number][] = []; // [response, x, y]
	for (let y = 1; y < rows - 1; y++) {
		for (let x = 1; x < cols - 1; x++) {
			const v = response[y * cols + x];
			if (v < threshold) continue;
			let isMax = true;
			for (let dy = -1; dy <= 1 && isMax; dy++) {
				for (let dx = -1; dx <= 1; dx++) {
					if ((dx || dy) && response[(y + dy) * cols + (x + dx)] > v) {
						isMax = false;
						break;
					}
				}
			}
			if (isMax) candidates.push([v, x, y]);
		}
	}
	candidates.sort((a, b) => b[0] - a[0]);

	// Greedy min-distance suppression on a cell grid (cell = minDist ⇒ only the
	// 3×3 neighborhood needs checking).
	const cell = Math.max(1, minDist);
	const gw = Math.ceil(cols / cell);
	const occupied = new Map<number, [number, number][]>();
	const out: [number, number][] = [];
	const minDistSq = minDist * minDist;
	for (const [, x, y] of candidates) {
		const cx = Math.floor(x / cell);
		const cy = Math.floor(y / cell);
		let ok = true;
		for (let ny = cy - 1; ny <= cy + 1 && ok; ny++) {
			for (let nx = cx - 1; nx <= cx + 1; nx++) {
				for (const [px, py] of occupied.get(ny * gw + nx) ?? []) {
					const ddx = px - x;
					const ddy = py - y;
					if (ddx * ddx + ddy * ddy < minDistSq) {
						ok = false;
						break;
					}
				}
				if (!ok) break;
			}
		}
		if (!ok) continue;
		out.push([x, y]);
		const key = cy * gw + cx;
		const bucket = occupied.get(key);
		if (bucket) bucket.push([x, y]);
		else occupied.set(key, [[x, y]]);
	}
	return out;
}

/**
 * Magnetic Cursor tool — snaps to corner/edge keypoints in the image.
 * Uses OpenCV.js goodFeaturesToTrack + Flatbush spatial index.
 *
 * Flow:
 * 1. On init: detect keypoints in image using OpenCV corner detection
 * 2. Build Flatbush spatial index for fast nearest-neighbor queries
 * 3. As cursor moves, snap to nearest keypoint within threshold
 * 4. Click to place points (snapped or unsnapped)
 * 5. Double-click or snap-to-first to close polygon
 */
export class MagneticTool implements Tool {
	readonly name = 'magnetic';
	readonly preview: Graphics;
	private ctx: InteractionContext;

	// Keypoint index
	private keypointIndex: Flatbush | null = null;
	private keypoints: [number, number][] = [];
	private ready = false;

	// Drawing state
	private points: number[] = [];
	private cursorX = 0;
	private cursorY = 0;
	private isSnapped = false;
	private isClosable = false;

	onCommit?: (shape: CommitShape) => void;
	/** Fires when the cursor snaps onto / off a detected corner — UI shows snap state. */
	onSnapChange?: (snapped: boolean) => void;

	constructor(ctx: InteractionContext) {
		this.ctx = ctx;
		this.preview = new Graphics();
		this.preview.label = 'magnetic-tool-preview';
		ctx.app.stage.addChild(this.preview);
	}

	/** Initialize with image element — detect keypoints */
	async initWithImage(imageElement: HTMLImageElement): Promise<void> {
		// Lazy shared load — the 8MB wasm is paid once across both CV tools.
		const cv = await loadOpenCV();

		// Render image to canvas
		const canvas = document.createElement('canvas');
		canvas.width = imageElement.naturalWidth;
		canvas.height = imageElement.naturalHeight;
		const ctx2d = canvas.getContext('2d')!;
		ctx2d.drawImage(imageElement, 0, 0);

		// Detect corners. `goodFeaturesToTrack` is NOT compiled into the opencv-js build
		// (verified against the installed dist), so we compute its core directly: the
		// min-eigenvalue corner-response map + quality threshold + local-maximum picking
		// (grid-suppressed min distance) — the same Shi–Tomasi corners, plain Mat ops only.
		const src = cv.imread(canvas);
		const gray = new cv.Mat();
		cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY, 0);

		const response = new cv.Mat();
		cv.cornerMinEigenVal(gray, response, 5, 3, cv.BORDER_DEFAULT);

		this.keypoints = pickCorners(
			response.data32F,
			response.cols,
			response.rows,
			0.001, // quality level (fraction of the max response)
			3, // min distance between corners (px)
		);
		// Build spatial index
		if (this.keypoints.length > 0) {
			this.keypointIndex = new Flatbush(this.keypoints.length);
			for (const [x, y] of this.keypoints) {
				this.keypointIndex.add(x, y, x, y);
			}
			this.keypointIndex.finish();
		}

		// Cleanup
		src.delete();
		gray.delete();
		response.delete();

		this.ready = true;
	}

	get isDrawing(): boolean {
		return this.points.length >= 2;
	}

	onPointerDown(x: number, y: number): boolean {
		if (this.isClosable) {
			this.commitPolygon();
			return true;
		}

		// Use snapped cursor position
		const px = this.isSnapped ? this.cursorX : x;
		const py = this.isSnapped ? this.cursorY : y;

		if (this.points.length === 0) {
			this.points = [px, py];
		} else {
			this.points.push(px, py);
		}

		return true;
	}

	onPointerMove(x: number, y: number): void {
		const wasSnapped = this.isSnapped;
		// Snap to nearest keypoint
		if (this.keypointIndex && this.keypoints.length > 0) {
			const maxDist = 15 / this.ctx.getViewportScale();
			const neighbors = this.keypointIndex.neighbors(x, y, 1, maxDist);

			if (neighbors.length > 0) {
				const [kx, ky] = this.keypoints[neighbors[0]];
				this.cursorX = kx;
				this.cursorY = ky;
				this.isSnapped = true;
			} else {
				this.cursorX = x;
				this.cursorY = y;
				this.isSnapped = false;
			}
		} else {
			this.cursorX = x;
			this.cursorY = y;
			this.isSnapped = false;
		}
		if (this.isSnapped !== wasSnapped) this.onSnapChange?.(this.isSnapped);

		// Check snap-to-close
		if (this.points.length >= 6) {
			const threshold = SNAP_THRESHOLD_PX / this.ctx.getViewportScale();
			this.isClosable = snapToPoint(
				this.cursorX,
				this.cursorY,
				this.points[0],
				this.points[1],
				threshold,
			);
		} else {
			this.isClosable = false;
		}

		if (this.points.length >= 2) {
			this.renderPreview();
		}
	}

	onPointerUp(_x: number, _y: number): void {
		// Magnetic tool uses click (pointerdown), not drag
	}

	onDoubleClick(_x: number, _y: number): void {
		if (this.points.length >= 6) {
			this.commitPolygon();
		}
	}

	onKeyDown(key: string): void {
		if (key === 'Escape') this.cancel();
		if (key === 'Enter' && this.points.length >= 6) {
			// Commit without the double-click / snap-to-close gesture (parity with Polygon/Brush).
			this.commitPolygon();
		}
		if (key === 'Backspace' && this.points.length >= 4) {
			this.points.pop();
			this.points.pop();
			this.renderPreview();
		}
	}

	cancel(): void {
		this.preview.clear();
		this.ctx.requestRender();
		this.points = [];
		this.isClosable = false;
		this.isSnapped = false;
	}

	destroy(): void {
		this.preview.destroy();
	}

	private commitPolygon(): void {
		if (this.points.length < 6) return;

		const bounds = boundsFromPolygon(this.points);
		this.preview.clear();
		this.ctx.requestRender(); // render-on-demand: repaint so the polygon doesn't ghost

		this.onCommit?.({
			type: 'polygon',
			x: bounds.x,
			y: bounds.y,
			width: bounds.w,
			height: bounds.h,
			polygon: [...this.points],
		});

		this.points = [];
		this.isClosable = false;
	}

	private renderPreview(): void {
		this.preview.clear();
		const scale = this.ctx.getViewportScale();
		const vertexR = 3 / scale;

		// Polygon edges + preview line to cursor
		const allPts = this.isClosable ? this.points : [...this.points, this.cursorX, this.cursorY];

		if (allPts.length >= 4) {
			this.preview.poly(allPts, this.isClosable);
			this.preview.fill({ color: STROKE_COLOR, alpha: 0.06 });
			this.preview.stroke({ color: STROKE_COLOR, width: 2 / scale });
		}

		// Vertex dots
		for (let i = 0; i < this.points.length; i += 2) {
			this.preview.circle(this.points[i], this.points[i + 1], vertexR);
			this.preview.fill({ color: HANDLE_FILL });
			this.preview.stroke({ color: STROKE_COLOR, width: 1 / scale });
		}

		// Cursor dot (larger when snapped)
		if (!this.isClosable) {
			const r = this.isSnapped ? 5 / scale : 3 / scale;
			this.preview.circle(this.cursorX, this.cursorY, r);
			this.preview.fill({
				color: this.isSnapped ? 0x22c55e : STROKE_COLOR,
				alpha: 0.8,
			});
			this.preview.stroke({ color: HANDLE_FILL, width: 1 / scale });
		}

		// Close indicator
		if (this.isClosable) {
			const r = 6 / scale;
			this.preview.circle(this.points[0], this.points[1], r);
			this.preview.fill({ color: STROKE_COLOR, alpha: 0.2 });
			this.preview.stroke({ color: STROKE_COLOR, width: 2 / scale });
		}

		this.ctx.requestRender();
	}
}
