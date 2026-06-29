import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// 2026-06-29: this middleware used to enforce a 307 redirect to /login
// when the kamilya_refresh cookie was missing on requests to protected
// routes. The intent was: "if we can't see the refresh cookie, the
// session is gone — kick the user back to login".
//
// That worked in dev. In production it broke login entirely, because
// the API lives on a different eTLD+1 (kamilya-lms-api.onrender.com)
// than the top-level site (app.kml.kz). Chrome's third-party cookie
// handling refused to attach the refresh cookie to the cross-origin
// response, so the Vercel Edge middleware never saw it and always
// redirected to /login — even for fresh successful logins.
//
// We tried adding SameSite=None; Secure; Partitioned to the cookie
// (commits 9054c99, 9ac09c0) — Chrome still doesn't expose it to the
// Vercel Edge in this environment. Rather than chase browser quirks,
// the auth check now lives entirely on the client: the Layout component
// (apps/web/src/components/layout/Layout.tsx) reads the auth store,
// waits for /auth/refresh to settle, and redirects to /login only when
// the session is definitively missing.
//
// This middleware is now a no-op pass-through. If we ever need true
// server-side auth gating (e.g. to protect RSC-fetched data), the
// path forward is: (a) move the API to a same-site subdomain like
// api.kml.kz so the cookie is naturally first-party, or (b) sign a
// short-lived JWT cookie that Edge can verify without round-tripping
// to the API. Both are out of scope for the 2026-06-29 hotfix.
export function middleware(request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  // Match the same paths as before so we don't accidentally widen the
  // surface area while removing the auth check.
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
