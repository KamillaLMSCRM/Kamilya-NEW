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
  // Proxy API requests to the FastAPI backend so the browser stays
  // same-origin (no CORS preflight, httpOnly refresh cookie works).
  // The auth module's in-memory session restore calls
  // `fetch('/api/v1/auth/refresh')` from `lib/auth.ts:restoreSession()`,
  // which only works if Next.js forwards `/api/v1/*` to Render.
  //
  // NOTE: `NEXT_PUBLIC_API_URL` on Vercel is set to
  //   `https://kamilya-lms-api.onrender.com/api`
  // — i.e. it already includes the `/api` segment so axios can build
  // paths like `${baseURL}/v1/auth/refresh`. Strip `/api` here and
  // re-attach `/api/v1` so the destination is `…onrender.com/api/v1/…`.
  async rewrites() {
    const raw = process.env.NEXT_PUBLIC_API_URL;
    if (!raw) return [];
    const stripped = raw.replace(/\/api\/?$/, '').replace(/\/$/, '');
    return [
      {
        source: '/api/v1/:path*',
        destination: `${stripped}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
