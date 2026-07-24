'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search } from 'lucide-react';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { getNavigationRoutes } from '@/lib/routeRegistry';

export default function CommandPalette() {
  const { t } = useT();
  const router = useRouter();
  const role = useAuthStore((state) => state.user?.role);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const routes = getNavigationRoutes(role, 'commandPalette');
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = normalizedQuery
    ? routes.filter((route) => t(route.labelKey!).toLocaleLowerCase().includes(normalizedQuery))
    : routes;

  if (!open) return <div className="hidden" id="cmd-palette-trigger" />;

  return (
    <div className="cmd-overlay" onClick={() => setOpen(false)}>
      <div className="cmd-box" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Search className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('commandPalette.placeholder')}
            className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            autoFocus
            aria-label={t('commandPalette.placeholder')}
          />
          <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">esc</kbd>
        </div>
        <div className="flex-1 overflow-y-auto p-2" role="listbox">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t('commandPalette.noResults')}</div>
          ) : filtered.map((route) => (
            <button
              key={route.id}
              type="button"
              onClick={() => {
                router.push(route.href);
                setOpen(false);
                setQuery('');
              }}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-foreground transition-colors hover:bg-muted"
            >
              <span>{t(route.labelKey!)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
