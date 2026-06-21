import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { getStoredAuth } from '@/lib/auth';

const protectedRoutes = ['/dashboard', '/settings', '/courses', '/positions', '/job-descriptions'];
const publicRoutes = ['/login', '/register', '/', '/legal'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Check if route is protected
  const isProtected = protectedRoutes.some((route) => pathname.startsWith(route));
  const isPublic = publicRoutes.some((route) => pathname === route || pathname.startsWith(route + '/'));

  if (isProtected) {
    const auth = getStoredAuth();
    if (!auth?.accessToken) {
      const url = request.nextUrl.clone();
      url.pathname = '/login';
      url.searchParams.set('redirect', pathname);
      return NextResponse.rewrite(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
