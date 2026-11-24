"use client";

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useT } from '@/i18n/useT';
import { getNavigationRoutes } from '@/lib/routeRegistry';
import { useAuthStore } from '@/store/authStore';

const sections = {
  courses: ['documents', 'quizzes', 'learning-paths-manage'],
  staff: ['positions', 'cohorts', 'candidate-assessments'],
  assignments: ['learning-cycles', 'methodologist-workbench'],
  trainingLog: ['mandatory-training', 'training-procedures', 'training-retention'],
} as const;

type ContextualItem = { label: string } & ({ href: string } | { onSelect: () => void });

const itemClass = 'flex min-h-11 w-full items-center md:min-h-10 rounded-lg px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export default function ContextualNavigation({ section, items = [] }: {
  section: keyof typeof sections;
  items?: ContextualItem[];
}) {
  const [alignEnd, setAlignEnd] = useState(false);
  const menuRef = useRef<HTMLDetailsElement>(null);
  const role = useAuthStore((state) => state.user?.role);
  const { t, lang } = useT();
  useEffect(() => {
    if (menuRef.current) menuRef.current.open = false;
  }, [section, role]);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      const menu = menuRef.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, []);
  if (role !== 'methodologist') return null;
  const routes = getNavigationRoutes(role, 'sidebar').filter((route) =>
    (sections[section] as readonly string[]).includes(route.id),
  );
  if (!routes.length && !items.length) return null;
  const close = () => {
    if (menuRef.current) menuRef.current.open = false;
  };
  const label = lang === 'kk' ? 'Тағы' : lang === 'en' ? 'More' : 'Ещё';
  return (
    <details ref={menuRef} className="relative" onKeyDown={(event) => {
      if (event.key !== 'Escape' || !event.currentTarget.open) return;
      event.preventDefault();
      event.currentTarget.open = false;
      event.currentTarget.querySelector('summary')?.focus();
    }} onBlur={(event) => {
      if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
    }} onToggle={(event) => {
      const menu = event.currentTarget;
      if (!menu.open) return;
      const anchor = menu.getBoundingClientRect();
      const contentLeft = menu.closest('main')?.getBoundingClientRect().left ?? 0;
      const menuWidth = Math.min(256, window.innerWidth - 32);
      setAlignEnd(anchor.right - menuWidth >= Math.max(16, contentLeft + 16));
    }}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center rounded-xl border border-border bg-card px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">{label}</summary>
      <ul className={`absolute ${alignEnd ? 'right-0' : 'left-0'} z-20 mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card p-1 shadow-lg`}>
        {items.map((item, index) => <li key={'href' in item ? 'link:' + item.href : 'action:' + index}>
          {'href' in item
            ? <Link href={item.href} onClick={close} className={itemClass}>{item.label}</Link>
            : <button type="button" className={itemClass} onClick={() => {
              close();
              menuRef.current?.querySelector('summary')?.focus();
              item.onSelect();
            }}>{item.label}</button>}
        </li>)}
        {routes.map((route) => <li key={route.id}><Link href={route.href} onClick={close} className={itemClass}>{t(route.labelKey!)}</Link></li>)}
      </ul>
    </details>
  );
}
