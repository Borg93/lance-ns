// $lib/gsap.ts
// Single place to import GSAP for the whole app (skill: gsap — "register once, on the client").
// Importing the module is SSR-safe; only *calling* gsap touches window/document, so the project
// defaults are set inside an `if (browser)` guard. Components import { gsap } from '$lib/gsap'.
//
// GSAP + every plugin is free since Webflow acquired GreenSock — public `gsap` package, no token.
import { browser } from '$app/environment';
import { gsap } from 'gsap';

if (browser) {
	// Project-wide tween defaults — every gsap.to()/from() inherits these.
	gsap.defaults({ ease: 'power3.out', duration: 0.5 });
}

/** True when the user asked for reduced motion. Client-only; false during SSR. */
export const reduced = (): boolean =>
	browser && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export { gsap };
