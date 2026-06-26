'use client';

import { usePathname } from 'next/navigation';
import Layout from '@/components/layout/Layout';

const publicRoutes = ['/', '/register'];
// Platform superadmin login lives outside any tenant layout — no sidebar,
// no AuthProvider tenant context required. Add the prefix so it stays
// render-bare like /login.
const publicPrefixes = ['/login', '/accept-invite', '/kiosk', '/superadmin'];

export default function RouteWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = publicRoutes.includes(pathname) || publicPrefixes.some((p) => pathname.startsWith(p));

  if (isPublic) {
    return <>{children}</>;
  }

  return <Layout>{children}</Layout>;
}
