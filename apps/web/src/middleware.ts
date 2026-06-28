import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const protectedRoutes = ['/dashboard', '/settings', '/courses', '/positions', '/job-descriptions', '/admin', '/ai/generate', '/documents', '/certificates', '/student', '/my-courses', '/my-quizzes'];
const publicRoutes = ['/login', '/register', '/', '/legal'];

// We check for the *refresh* cookie (kamilya_refresh), not the access token.
// The access token is held in-memory only and is not visible to middleware.
// If the refresh cookie exists, the user has a valid long-lived session.
// The Layout component then calls /auth/refresh to materialize the access
// token before any API call.
const REFRESH_COOKIE = 'kamilya_refresh';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));

  if (isProtected) {
    const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
    if (!refreshToken) {
      const url = request.nextUrl.clone();
      url.pathname = '/login';
      url.searchParams.set('redirect', pathname);
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
