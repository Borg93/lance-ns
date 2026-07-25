# @repo/zone-contract

The zone manifest is declared in **four** places that must agree, none of which the type system or a
build can relate to each other:

| Declares                                       | Where                                           |
| ---------------------------------------------- | ----------------------------------------------- |
| which paths a zone owns, and its dev port      | `components/frontends/home/microfrontends.json` |
| the base path the zone serves its assets under | `components/frontends/<zone>/svelte.config.js`  |
| the dev port the zone actually binds           | `components/frontends/<zone>/vite.config.ts`    |
| the Ingress route and Service in the cluster   | `chart/values.yaml` → `frontend.apps`           |

A disagreement is invisible until someone clicks a cross-zone link. It has already happened twice:
`media` and `annotator` were missing from the routing config entirely while being real, Ingress-routed
zones, and `annotator` bound the same dev port as `models` without `strictPort`, so under
`turbo run dev` it silently drifted and every `/annotator` link landed on the models app.

This package is the gate. It is the "make it mechanical" half of the micro-frontends team-prefix
principle, applied to the zone manifest instead of to CSS class names.
