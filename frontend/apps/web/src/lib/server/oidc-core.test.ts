/**
 * Unit tests for the security-critical OIDC logic — runs under `bun test` (no extra deps; Bun ships
 * Web Crypto + a Jest-like runner). The network glue + SvelteKit routes are type-checked by svelte-check
 * and verified end-to-end against a live Dex; here we pin the pure pieces that are easy to get subtly wrong.
 */
import { describe, expect, test } from "bun:test";

import {
	type OidcConfig,
	type Session,
	base64url,
	base64urlDecode,
	buildAuthorizeUrl,
	decodeJwtClaims,
	decodeSession,
	encodeSession,
	exchangeCode,
	isExpired,
	pkceChallenge,
	randomToken,
	sessionFromTokens,
	tokenRequestBody,
} from "./oidc-core";

const CFG: OidcConfig = {
	issuer: "https://dex.example.com",
	clientId: "lance-web",
	clientSecret: null,
	redirectUri: "https://app.example.com/auth/callback",
	scopes: "openid profile email",
};

/** A JWT with the given claims payload (header/sig are throwaway — we never verify the sig in the BFF). */
function jwtWith(claims: Record<string, unknown>): string {
	return `header.${base64url(new TextEncoder().encode(JSON.stringify(claims)))}.sig`;
}

describe("base64url", () => {
	test("round-trips arbitrary UTF-8 bytes", () => {
		const text = "naïve ✓ a/b+c=";
		expect(base64urlDecode(base64url(new TextEncoder().encode(text)))).toBe(text);
	});

	test("is url-safe and unpadded", () => {
		const encoded = base64url(new Uint8Array([251, 255, 191, 0]));
		expect(encoded).not.toMatch(/[+/=]/);
	});
});

describe("PKCE", () => {
	test("S256 challenge matches the RFC 7636 appendix-B test vector", async () => {
		// The canonical example from RFC 7636 §4.1/Appendix B — proves our S256 encoding is byte-correct.
		const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
		expect(await pkceChallenge(verifier)).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
	});

	test("randomToken is url-safe and high-entropy (distinct per call)", () => {
		const a = randomToken();
		const b = randomToken();
		expect(a).not.toBe(b);
		expect(a).not.toMatch(/[+/=]/);
	});
});

describe("authorize URL", () => {
	test("carries response_type=code, the client/redirect/scope, state, and S256 challenge", () => {
		const url = new URL(buildAuthorizeUrl(CFG, `${CFG.issuer}/auth`, "st4te", "ch4llenge"));
		const p = url.searchParams;
		expect(p.get("response_type")).toBe("code");
		expect(p.get("client_id")).toBe("lance-web");
		expect(p.get("redirect_uri")).toBe(CFG.redirectUri);
		expect(p.get("scope")).toBe("openid profile email");
		expect(p.get("state")).toBe("st4te");
		expect(p.get("code_challenge")).toBe("ch4llenge");
		expect(p.get("code_challenge_method")).toBe("S256");
	});
});

describe("token request body", () => {
	test("is an authorization_code grant carrying the PKCE verifier (no secret for a public client)", () => {
		const body = tokenRequestBody(CFG, "the-code", "the-verifier");
		expect(body.get("grant_type")).toBe("authorization_code");
		expect(body.get("code")).toBe("the-code");
		expect(body.get("code_verifier")).toBe("the-verifier");
		expect(body.get("client_id")).toBe("lance-web");
		expect(body.get("client_secret")).toBeNull();
	});

	test("includes the client_secret for a confidential client", () => {
		const body = tokenRequestBody({ ...CFG, clientSecret: "s3cret" }, "c", "v");
		expect(body.get("client_secret")).toBe("s3cret");
	});
});

describe("JWT + session", () => {
	test("decodeJwtClaims reads the (unverified) payload", () => {
		expect(decodeJwtClaims(jwtWith({ sub: "u1", name: "Dee" })).name).toBe("Dee");
	});

	test("decodeJwtClaims rejects a malformed token", () => {
		expect(() => decodeJwtClaims("not-a-jwt")).toThrow();
	});

	test("sessionFromTokens lifts sub/name/email/exp + binds the access token", () => {
		const s = sessionFromTokens(
			jwtWith({ sub: "u1", name: "Dee", email: "dee@x.io", exp: 4102444800 }),
			"AT-123",
		);
		expect(s).toEqual({
			sub: "u1",
			name: "Dee",
			email: "dee@x.io",
			accessToken: "AT-123",
			expiresAt: 4102444800,
		});
	});

	test("sessionFromTokens falls back through preferred_username → email → sub for the display name", () => {
		expect(sessionFromTokens(jwtWith({ sub: "u2", preferred_username: "pu" }), "AT").name).toBe(
			"pu",
		);
		expect(sessionFromTokens(jwtWith({ sub: "u3" }), "AT").name).toBe("u3");
	});

	test("encode/decode session round-trips; a tampered/empty cookie decodes to null", () => {
		const s: Session = { sub: "u1", name: "Dee", email: null, accessToken: "AT", expiresAt: 0 };
		expect(decodeSession(encodeSession(s))).toEqual(s);
		expect(decodeSession("@@not-base64@@")).toBeNull();
		expect(decodeSession(base64url(new TextEncoder().encode("{}")))).toBeNull(); // no sub/token
	});

	test("isExpired honors exp; exp=0 (no claim) is treated as live", () => {
		expect(
			isExpired({ sub: "u", name: "n", email: null, accessToken: "a", expiresAt: 100 }, 200),
		).toBe(true);
		expect(
			isExpired({ sub: "u", name: "n", email: null, accessToken: "a", expiresAt: 300 }, 200),
		).toBe(false);
		expect(
			isExpired({ sub: "u", name: "n", email: null, accessToken: "a", expiresAt: 0 }, 200),
		).toBe(false);
	});
});

describe("exchangeCode", () => {
	test("POSTs the code-grant body and lifts the token response into a session", async () => {
		let captured: { url: string; body: string } | null = null;
		const fakeFetch = (async (url: string | URL | Request, init?: RequestInit) => {
			captured = { url: String(url), body: String(init?.body) };
			return new Response(
				JSON.stringify({ access_token: "AT-xyz", id_token: jwtWith({ sub: "u9", name: "Nine" }) }),
				{ status: 200, headers: { "content-type": "application/json" } },
			);
		}) as typeof fetch;

		const session = await exchangeCode(CFG, `${CFG.issuer}/token`, "code-1", "ver-1", fakeFetch);
		expect(session.sub).toBe("u9");
		expect(session.accessToken).toBe("AT-xyz");
		expect(captured!.url).toBe(`${CFG.issuer}/token`);
		expect(captured!.body).toContain("grant_type=authorization_code");
		expect(captured!.body).toContain("code_verifier=ver-1");
	});

	test("throws on a non-2xx token response (so the callback fails closed)", async () => {
		const fakeFetch = (async () =>
			new Response("nope", { status: 401 })) as unknown as typeof fetch;
		await expect(exchangeCode(CFG, `${CFG.issuer}/token`, "c", "v", fakeFetch)).rejects.toThrow();
	});
});
