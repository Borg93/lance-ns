// Re-export shim: the OIDC BFF crypto seam MOVED to @rask/api (the shared MFE package). apps/web keeps
// this thin re-export so its many importers ($lib/server/oidc, hooks.server, /auth routes) stay green
// through the MFE migration; both apps/web and the zones now consume ONE source of truth. Deleted at P5
// when apps/web is retired.
export * from "@rask/api/oidc";
