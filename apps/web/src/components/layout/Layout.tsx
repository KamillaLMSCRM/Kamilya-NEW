'use client';

import { useEffect, useRef, useState, createContext, useContext } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import CommandPalette from '@/components/CommandPalette';
import { api } from '@/lib/api';
import { toast } from '@/components/ui/Toast';
import { DemoLimitProvider } from '@/components/demo/DemoLimitProvider';
import { DemoBanner } from '@/components/demo/DemoBanner';

const SidebarContext = createContext({ collapsed: false });

export function useSidebarCollapsed() {
  return useContext(SidebarContext);
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useT();
  const { user, initialize } = useAuthStore();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  // Track active generation to surface a toast when it finishes (so a user
  // who navigated away still gets notified). The /ai/generate page itself
  // owns its own progress UI; we don't render anything visible at the
  // Layout level.
  const lastNotifiedJobRef = useRef<string | null>(null);

  useEffect(() => {
    initialize();
  }, [initialize]);

  // Redirect-to-login guard. MUST wait for `initialized` from the auth
  // store, otherwise this fires on every fresh mount of Layout with
  // accessToken=null in the Zustand store (because the store was
  // initialised before the in-memory lib/auth token was populated),
  // and we send the user back to /login even when they have a valid
  // session that was just minted by /login polling.
  //
  // Fix for 2026-06-29 login-bounce bug — see docs/LOGIN_BUG_REPORT_2026-06-29.md.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const state = useAuthStore.getState();
    // eslint-disable-next-line no-console
    console.log('[layout-guard] tick', {
      initialized: state.initialized,
      hasAccessToken: !!state.accessToken,
      pathname,
    });
    if (!state.initialized) return;  // wait for /auth/refresh to settle
    if (!state.accessToken) {
      // eslint-disable-next-line no-console
      console.log('[layout-guard] REDIRECT to /login');
      router.push('/login');
    }
  }, [router, pathname]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Poll active generation job from localStorage — survives SPA navigation.
  // The /ai/generate page owns the progress UI; here we only fire a toast
  // notification when a job transitions to a terminal state so the user
  // who navigated away still learns the outcome.
  // IMPORTANT: do NOT remove the job id on transient network errors; the
  // Celery worker keeps running on the backend. Only drop when the backend
  // confirms terminal state or returns 404.
  useEffect(() => {
    const checkActiveJob = async () => {
      const jobId = localStorage.getItem('ai_active_job_id');
      if (!jobId) return;
      try {
        const res = await api.get(`/v1/ai/jobs/${jobId}`);
        const status = res.data.status;
        if (status === 'completed' || status === 'failed' || status === 'cancelled') {
          // Notify once per job id, only if we hadn't already.
          if (lastNotifiedJobRef.current !== jobId) {
            lastNotifiedJobRef.current = jobId;
            if (status === 'completed') {
              toast.success(t('toast.generationComplete' as any) || 'Курс готов');
            } else if (status === 'failed') {
              toast.error(t('toast.generationFailed' as any) || 'Не удалось сгенерировать курс');
            } else {
              toast.warning(t('toast.generationCancelled' as any) || 'Генерация отменена');
            }
          }
          localStorage.removeItem('ai_active_job_id');
        }
      } catch (err: any) {
        // Transient error — keep the job id; the /ai/generate page will
        // pick it back up via restoreActiveJob() when the user returns.
        if (err?.response?.status === 404) {
          localStorage.removeItem('ai_active_job_id');
          lastNotifiedJobRef.current = jobId;
        }
      }
    };
    checkActiveJob();
    const interval = setInterval(checkActiveJob, 10000);
    return () => clearInterval(interval);
  }, [t]);

  // Hooks must be called unconditionally on every render — keep them
  // above any early-return so React's order-of-hooks rule is satisfied.
  // (pathname is already declared at the top of the component for the
  // redirect-to-login guard.)
  const isSuperadmin = user?.role === 'superadmin' && user.tenant == null;

  if (!user) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div
            className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent"
            aria-label={t('common.loading')}
          />
          <p className="text-muted-foreground text-sm">{t('common.loading')}</p>
        </div>
      </div>
    );
  }

  // Platform superadmin (tenant_id IS NULL → user.tenant is null on the
  // frontend) should only see platform-level pages. Anything else is a
  // tenant-scoped page that would return 403 on every API call.
  // Whitelist the platform paths they ARE allowed to visit; redirect
  // everything else to /admin/super.
  const SUPERADMIN_ALLOWED_PREFIXES = [
    '/admin/super',
    '/admin/providers',
    '/superadmin',     // login form (already public, but defense in depth)
  ];
  if (
    isSuperadmin &&
    pathname &&
    !SUPERADMIN_ALLOWED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))
  ) {
    if (typeof window !== 'undefined') {
      router.replace('/admin/super');
    }
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Redirecting…</p>
      </div>
    );
  }

  // Inverse guard: tenant user (not superadmin) trying to reach a
  // platform-level page → back to their dashboard.
  if (
    !isSuperadmin &&
    pathname &&
    (pathname.startsWith('/admin/super') || pathname.startsWith('/admin/providers'))
  ) {
    if (typeof window !== 'undefined') {
      router.replace('/dashboard');
    }
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Redirecting…</p>
      </div>
    );
  }

  // Tenant admins own company administration and compliance oversight. They
  // do not author courses, manage learners, or make learning assignments.
  // Keep direct URLs consistent with the role-aware sidebar instead of
  // allowing a stale bookmark to open a learning-management screen.
  const isTenantAdmin = user.role === 'admin' || user.role === 'org_admin';
  const TENANT_ADMIN_BLOCKED_PREFIXES = [
    '/ai',
    '/learning-paths',
    '/cohorts',
    '/competencies',
    '/surveys',
    '/announcements',
    '/courses',
    '/quizzes',
    '/documents',
    '/staff',
    '/positions',
    '/assignments',
    '/admin/staff',
    '/admin/quizzes',
    '/admin/invitations',
    '/my-courses',
    '/my-quizzes',
  ];
  if (
    isTenantAdmin &&
    pathname &&
    TENANT_ADMIN_BLOCKED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))
  ) {
    if (typeof window !== 'undefined') {
      router.replace('/admin');
    }
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Переходим в панель компании...</p>
      </div>
    );
  }

  return (
    <DemoLimitProvider>
      <SidebarContext.Provider value={{ collapsed }}>
        <div className="min-h-screen bg-background grain">
          <Sidebar
            collapsed={collapsed}
            mobileOpen={mobileSidebarOpen}
            onToggle={() => setCollapsed((c) => !c)}
            onClose={() => setMobileSidebarOpen(false)}
          />
          {mobileSidebarOpen && (
            <button
              type="button"
              className="fixed inset-0 z-20 bg-black/30 md:hidden"
              aria-label={t('sidebar.close') || 'Закрыть меню'}
              onClick={() => setMobileSidebarOpen(false)}
            />
          )}
          <CommandPalette />
          <main
            className={collapsed ? 'ml-0 transition-all duration-300 md:ml-[68px]' : 'ml-0 transition-all duration-300 md:ml-[240px]'}
          >
            <DemoBanner />
            <TopBar onMenuClick={() => setMobileSidebarOpen(true)} />
            <div className="p-6">{children}</div>
          </main>
        </div>
      </SidebarContext.Provider>
    </DemoLimitProvider>
  );
}
