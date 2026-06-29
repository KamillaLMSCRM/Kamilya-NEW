/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typescript: {
    ignoreBuildErrors: false,
  },
  eslint: {
    ignoreDuringBuilds: false,
  },
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'cdn.lms.kml.kz',
      },
    ],
  },
  // API calls now go cross-origin directly to the FastAPI backend.
// Earlier we had a `rewrites()` block that proxied /api/v1/* through
// Next.js — same-origin meant no CORS preflight, but Vercel's edge
// strips Set-Cookie on proxied responses, which broke the httpOnly
// refresh-cookie round-trip (every page reload kicked the user back
// to /login).
//
// Going cross-origin instead: CORS is already configured in
// apps/api/app/main.py (ALLOWED_ORIGINS includes https://app.kml.kz),
// and the browser stores the httpOnly refresh cookie normally.
//
// axios uses NEXT_PUBLIC_API_URL directly (lib/api.ts).
// lib/auth.ts uses NEXT_PUBLIC_API_URL + '/api/v1/auth/...' for
// the in-memory refresh round-trip outside the axios instance.
};

module.exports = nextConfig;
