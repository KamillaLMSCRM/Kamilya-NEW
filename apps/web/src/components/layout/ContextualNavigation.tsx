"use client";

import Link from 'next/link';
import { useState } from 'react';
import { useT } from '@/i18n/useT';
import { getNavigationRoutes } from '@/lib/routeRegistry';
import { useAuthStore } from '@/store/authStore';

const sections = {
  courses: ['documents', 'quizzes', 'learning-paths-manage'],
  staff: ['positions', 'cohorts', 'candidate-assessments'],
  assignments: ['learning-cycles', 'methodologist-workbench'],
  trainingLog: ['mandatory-training', 'training-procedures', 'training-retention'],
} as const;

export default function ContextualNavigation({ section }: { section: keyof typeof sections }) {
  const [alignEnd, setAlignEnd] = useState(false);
  const role = useAuthStore((state) => state.user?.role);
  const { t, lang } = useT();
  if (role !== 'methodologist') return null;
  const routes = getNavigationRoutes(role, 'sidebar').filter((route) =>
    (sections[section] as readonly string[]).includes(route.id),
  );
  if (!routes.length) return null;
  const label = lang === 'kk' ? 'Тағы' : lang === 'en' ? 'More' : 'Ещё';
  return (
    <details className="relative" onToggle={(event) => {
      const menu = event.currentTarget;
      if (!menu.open) return;
      const anchor = menu.getBoundingClientRect();
      const contentLeft = menu.closest('main')?.getBoundingClientRect().left ?? 0;
      const menuWidth = Math.min(256, window.innerWidth - 32);
      setAlignEnd(anchor.right - menuWidth >= Math.max(16, contentLeft + 16));
    }}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center rounded-xl border border-border bg-card px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">{label}</summary>
      <ul className={`absolute ${alignEnd ? 'right-0' : 'left-0'} z-20 mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card p-1 shadow-lg`}>
        {routes.map((route) => <li key={route.id}><Link href={route.href} className="block rounded-lg px-3 py-2 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t(route.labelKey!)}</Link></li>)}
      </ul>
    </details>
  );
}
