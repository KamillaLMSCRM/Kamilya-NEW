'use client';

import { useEffect, useState, createContext, useContext } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import CommandPalette from '@/components/CommandPalette';
import { api } from '@/lib/api';
import { Loader2 } from 'lucide-react';

const SidebarContext = createContext({ collapsed: false });

export function useSidebarCollapsed() {
  return useContext(SidebarContext);
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { t } = useT();
  const { user, initialize } = useAuthStore();
  const [collapsed, setCollapsed] = useState(false);
  const [activeJob, setActiveJob] = useState<{ id: string; progress: number; stage: string } | null>(null);

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (typeof window !== 'undefined' && !useAuthStore.getState().accessToken) {
      router.push('/login');
    }
  }, [router]);

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
  // IMPORTANT: do NOT remove the job id from localStorage on transient network
  // errors (the Celery worker keeps running on the backend). Only remove when
  // the backend explicitly confirms a terminal state (completed/failed/cancelled)
  // or returns 404 (job truly gone). This lets the user navigate away and back
  // without losing the job reference if a transient 5xx / network blip happens.
  useEffect(() => {
    const checkActiveJob = async () => {
      const jobId = localStorage.getItem('ai_active_job_id');
      if (!jobId) { setActiveJob(null); return; }
      try {
        const res = await api.get(`/v1/ai/jobs/${jobId}`);
        const status = res.data.status;
        if (status === 'running' || status === 'pending') {
          setActiveJob({ id: res.data.id, progress: res.data.progress, stage: res.data.stage });
        } else {
          // Terminal state — backend confirmed job is done/failed/cancelled
          localStorage.removeItem('ai_active_job_id');
          setActiveJob(null);
        }
      } catch (err: any) {
        // Transient error (network blip, 5xx, etc.) — keep the job id in
        // localStorage so restoreActiveJob() can pick it up when the user
        // navigates back to /ai/generate. Hide the widget for now.
        const code = err?.response?.status;
        if (code === 404) {
          // Job truly doesn't exist on backend anymore — safe to drop
          localStorage.removeItem('ai_active_job_id');
        }
        setActiveJob(null);
      }
    };
    checkActiveJob();
    const interval = setInterval(checkActiveJob, 10000);
    return () => clearInterval(interval);
  }, []);

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

  return (
    <SidebarContext.Provider value={{ collapsed }}>
      <div className="min-h-screen bg-background grain">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <CommandPalette />
        <main
          className="transition-all duration-300"
          style={{ marginLeft: collapsed ? 68 : 240 }}
        >
          <TopBar />
          <div className="p-6">{children}</div>
        </main>
        {/* Floating generation progress widget — bottom-right, dismissible look */}
        {activeJob && (
          <Link
            href="/ai/generate"
            className="fixed bottom-4 right-4 z-30 flex items-center gap-3 rounded-full border border-primary/30 bg-card/95 px-4 py-2.5 text-sm text-primary shadow-card-lg backdrop-blur-sm hover:bg-card hover:shadow-card-hover transition-all"
            role="status"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            <span className="font-medium">{t('toast.generationStarted')} · {activeJob.progress}%</span>
            <span className="hidden sm:inline text-primary/60">· {activeJob.stage}</span>
          </Link>
        )}
      </div>
    </SidebarContext.Provider>
  );
}
