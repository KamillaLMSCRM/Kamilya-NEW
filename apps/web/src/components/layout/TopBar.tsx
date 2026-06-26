'use client';

import { useState, useRef, useEffect } from 'react';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

interface TopBarProps {
  title?: string;
}

export default function TopBar({ title }: TopBarProps) {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
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

  const isImpersonating = !!user?.impersonated_by;
  const isSuperadmin = !!user && user.tenant == null && !isImpersonating;

  const exitImpersonation = () => {
    // Impersonation is a one-shot session: the only way out is to
    // re-authenticate as the platform superadmin. Wipe local storage
    // and route back to the superadmin login form.
    logout();
    if (typeof window !== 'undefined') {
      window.location.href = '/superadmin/login';
    }
  };

  const goToSuperadmin = () => {
    // The current user is a tenant admin whose telegram_id also
    // belongs to the platform superadmin (same identity, different
    // tenant rows). Swap to the superadmin session by re-logging-in
    // via the email/password form.
    if (typeof window !== 'undefined') {
      window.location.href = '/superadmin/login';
    }
  };

  return (
    <header className="sticky top-0 z-20 flex flex-col bg-card/80 backdrop-blur-md border-b border-border">
      {/* Impersonation banner — visible whenever this session was minted
          by POST /admin/super/tenants/{id}/impersonate. Shows the operator
          what they look like to the backend and gives a single-click exit. */}
      {isImpersonating && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 bg-warning/10 border-b border-warning/20 px-6 py-2 text-sm text-warning"
        >
          <div className="flex items-center gap-2 min-w-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="shrink-0">
              <path d="M12 9v4" />
              <path d="M12 17h.01" />
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
            </svg>
            <span className="truncate">
              <strong>Вы как суперадмин:</strong> видите систему как{' '}
              <strong>{user?.tenant?.name || 'тенант'}</strong>{' '}
              <span className="text-warning/70">({user?.impersonated_role})</span>
            </span>
          </div>
          <button
            type="button"
            onClick={exitImpersonation}
            className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-warning/30 px-2.5 py-1 text-xs font-medium text-warning hover:bg-warning/15 transition-colors"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" x2="9" y1="12" y2="12" />
            </svg>
            Выйти
          </button>
        </div>
      )}

      <div className="flex h-16 items-center justify-between px-6">
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

        {/* Super admin switch — only visible to tenant users whose
            telegram_id is also bound to the platform superadmin row.
            Clicking routes to the superadmin login form. The actual
            swap happens after re-auth. */}
        {!isSuperadmin && !isImpersonating && (
          <button
            type="button"
            onClick={goToSuperadmin}
            className="inline-flex items-center gap-1.5 rounded-xl border border-warning/40 bg-warning/5 px-3 py-2 text-xs font-medium text-warning hover:bg-warning/15 transition-colors"
            title="Войти как оператор платформы"
            aria-label="Войти как суперадмин"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            Super admin
          </button>
        )}
      </div>
      </div>
    </header>
  );
}
