/** @lance/ui — the shared Svelte 5 component library (rask convention: apps/* consume
 * transport-agnostic components from packages/ui; the fold-in becomes a directory graft). */
export { default as Chip } from "./Chip.svelte";
export { default as Select } from "./Select.svelte";
export { default as SearchBar } from "./SearchBar.svelte";
export type { SearchHit } from "./SearchBar.svelte";
export { default as StatusBoard } from "./StatusBoard.svelte";
export type { RunStatusLike } from "./StatusBoard.svelte";
// GSAP {@attach} factories — the workspace's animation primitives (reduced-motion aware, SSR-safe).
export { bar, breathe, countUp, enter, pop, pulse, stagger } from "./attachments";
