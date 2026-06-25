'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';

interface CommandItem {
  label: string;
  href?: string;
  icon: React.ReactNode;
  keywords?: string[];
}

export default function CommandPalette() {
  const { t } = useT();
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === 'Escape') {
        setOpen(false);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const allItems: CommandItem[] = [
    { label: t('nav.dashboard'), href: '/dashboard', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg> },
    { label: t('nav.courses'), href: '/courses', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg> },
    { label: t('nav.documents'), href: '/documents', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg> },
    { label: t('nav.aiGeneration'), href: '/ai/generate', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z"/><circle cx="12" cy="15" r="2"/></svg> },
    { label: 'Должности', href: '/positions', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg> },
    { label: t('student.enrolledCourses'), href: '/my-courses', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 6 3 12 0v-5"/></svg> },
    { label: t('nav.certificates'), href: '/certificates', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/></svg> },
  ];

  if (user?.role && ['admin', 'superadmin'].includes(user.role)) {
    allItems.push(
      { label: t('nav.userManagement'), href: '/admin/users', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
      { label: t('courses.enrollments'), href: '/admin/enrollments', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" x2="19" y1="8" y2="14"/><line x1="22" x2="16" y1="11" y2="11"/></svg> },
      { label: t('quiz.title'), href: '/admin/quizzes', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> },
      { label: t('nav.admin'), href: '/admin', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg> }
    );
  }

  allItems.push(
    { label: t('settings.title'), href: '/settings', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/></svg> },
  );

  const filtered = query
    ? allItems.filter((item) => {
        const q = query.toLowerCase();
        return (
          item.label.toLowerCase().includes(q) ||
          item.keywords?.some((k) => k.toLowerCase().includes(q))
        );
      })
    : allItems;

  const handleSelect = (href: string) => {
    router.push(href);
    setOpen(false);
    setQuery('');
  };

  return (
    <>
      {/* Hidden trigger for programmatic open */}
      <div className="hidden" id="cmd-palette-trigger" />

      {open && (
        <div className="cmd-overlay" onClick={() => setOpen(false)}>
          <div
            className="cmd-box"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-border px-4 py-3">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground shrink-0">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('commandPalette.placeholder')}
              className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
              autoFocus
              aria-label={t('commandPalette.placeholder')}
            />
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                esc
              </kbd>
            </div>

            {/* Results */}
            <div className="flex-1 overflow-y-auto p-2" role="listbox">
              {filtered.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                  {t('commandPalette.noResults')}
                </div>
              ) : (
                filtered.map((item) => (
                  <button
                    key={item.href}
                    onClick={() => handleSelect(item.href!)}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-foreground hover:bg-muted transition-colors"
                  >
                    <span className="text-muted-foreground">{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))
              )}
            </div>

      {/* Footer */}
      <div className="border-t border-border px-4 py-2.5 text-[11px] text-muted-foreground flex items-center gap-4">
        <span className="flex items-center gap-1">
          <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono">↑↓</kbd>
          {t('commandPalette.navigation')}
        </span>
        <span className="flex items-center gap-1">
          <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono">↵</kbd>
          {t('commandPalette.select')}
        </span>
        <span className="flex items-center gap-1">
          <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono">esc</kbd>
          {t('commandPalette.close')}
        </span>
      </div>
          </div>
        </div>
      )}
    </>
  );
}
