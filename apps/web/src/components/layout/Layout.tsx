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
import { getAuthRedirect } from '@/lib/rolePolicy';

const SidebarContext = createContext({ collapsed: false });

export function useSidebarCollapsed() {
  return useContext(SidebarContext);
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useT();
  const { user, accessToken, initialized, initialize } = useAuthStore();
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

  const authRedirect = getAuthRedirect({
    initialized,
    accessToken,
    role: user?.role,
    pathname,
  });

  useEffect(() => {
    if (authRedirect) router.replace(authRedirect);
  }, [authRedirect, router]);

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

  if (!initialized || !accessToken || !user || authRedirect) {
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
