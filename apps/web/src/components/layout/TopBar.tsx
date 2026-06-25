'use client';

import { useState, useRef, useEffect } from 'react';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

interface TopBarProps {
  title?: string;
}

export default function TopBar({ title }: TopBarProps) {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const [showNotifications, setShowNotifications] = useState(false);
  const notificationsRef = useRef<HTMLDivElement>(null);

  // Close notifications on Escape
  useEffect(() => {
    if (!showNotifications) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setShowNotifications(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showNotifications]);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-card/80 backdrop-blur-md px-6">
      {/* Left: Page title */}
      <div>
        {title && (
          <h1 className="text-lg font-bold text-foreground font-display">{title}</h1>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-3">
        {/* Language switcher */}
        <LanguageSwitcher />

        {/* Cmd+K search */}
        <button
          onClick={() => {
            window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }));
          }}
          className="hidden sm:flex items-center gap-2 rounded-xl border border-border bg-muted px-3 py-2 text-sm text-muted-foreground hover:border-border hover:text-foreground transition-colors"
          aria-label={t('topbar.openCommandPalette') || 'Open command palette'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <span className="text-muted-foreground">{t('common.search')}</span>
          <kbd className="ml-4 rounded border border-border bg-card px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground" aria-hidden="true">
            ⌘K
          </kbd>
        </button>

        {/* Notifications */}
        <div className="relative" ref={notificationsRef}>
          <button
            onClick={() => setShowNotifications(!showNotifications)}
            className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-border text-muted-foreground hover:border-border hover:text-foreground transition-colors"
            aria-label={t('topbar.notifications')}
            aria-expanded={showNotifications}
            aria-haspopup="true"
            aria-controls="notifications-dropdown"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
              <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            {/* Notification dot */}
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-card bg-gold-500" aria-hidden="true" />
          </button>

          {/* Notifications dropdown */}
          {showNotifications && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)} aria-hidden="true" />
              <div
                id="notifications-dropdown"
                role="menu"
                aria-label={t('topbar.notifications')}
                className="absolute right-0 top-12 z-50 w-80 rounded-2xl border border-border bg-card shadow-card-lg overflow-hidden"
              >
                <div className="border-b border-border px-4 py-3">
                  <h3 className="text-sm font-bold text-foreground font-display">{t('topbar.notifications')}</h3>
                </div>
                <div className="max-h-80 overflow-y-auto p-2">
                  <div className="rounded-xl px-3 py-3 text-center text-sm text-muted-foreground">
                    {t('topbar.noNotifications')}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Avatar — name shown in Sidebar footer, TopBar only shows initials */}
        <div
          className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
          aria-label={user?.full_name || 'User'}
          title={user?.full_name}
        >
          {user?.full_name?.[0] || '?'}
        </div>
      </div>
    </header>
  );
}
