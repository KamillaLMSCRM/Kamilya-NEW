'use client';

// ADR-0011: /admin/employees is now consolidated into /admin/staff as the
// "Структура" tab. This file remains only as a redirect so legacy bookmarks
// and old links don't 404. Will be removed in v1.1 alongside the legacy
// /admin/staff/tree backend shim.

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

export default function AdminEmployeesRedirect() {
  const router = useRouter();
  const search = useSearchParams();

  useEffect(() => {
    const qs = search?.toString() ?? '';
    const target = qs ? `/staff?${qs}&tab=structure` : '/staff?tab=structure';
    router.replace(target);
  }, [router, search]);

  return (
    <div className="p-6 text-muted-foreground">
      Перенаправляю в <a className="text-primary underline" href="/staff?tab=structure">Штатное расписание → Структура</a>…
    </div>
  );
}
