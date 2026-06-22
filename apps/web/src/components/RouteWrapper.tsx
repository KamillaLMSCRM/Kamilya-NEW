'use client';

import { usePathname } from 'next/navigation';
import Layout from '@/components/layout/Layout';

const publicRoutes = ['/', '/login', '/register'];

export default function RouteWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = publicRoutes.includes(pathname);

  if (isPublic) {
    return <>{children}</>;
  }

  return <Layout>{children}</Layout>;
}
