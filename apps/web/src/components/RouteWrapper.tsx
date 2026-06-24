'use client';

import { usePathname } from 'next/navigation';
import Layout from '@/components/layout/Layout';

const publicRoutes = ['/', '/register'];
const publicPrefixes = ['/login'];

export default function RouteWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = publicRoutes.includes(pathname) || publicPrefixes.some((p) => pathname.startsWith(p));

  if (isPublic) {
    return <>{children}</>;
  }

  return <Layout>{children}</Layout>;
}
