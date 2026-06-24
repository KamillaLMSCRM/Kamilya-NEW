'use client';

import { useEffect, useState, createContext, useContext } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
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

  // Poll active generation job from localStorage
  useEffect(() => {
    const checkActiveJob = async () => {
      const jobId = localStorage.getItem('ai_active_job_id');
      if (!jobId) { setActiveJob(null); return; }
      try {
        const res = await api.get(`/v1/ai/jobs/${jobId}`);
        if (res.data.status === 'running' || res.data.status === 'pending') {
          setActiveJob({ id: res.data.id, progress: res.data.progress, stage: res.data.stage });
        } else {
          localStorage.removeItem('ai_active_job_id');
          setActiveJob(null);
        }
      } catch {
        setActiveJob(null);
      }
    };
    checkActiveJob();
    const interval = setInterval(checkActiveJob, 10000);
    return () => clearInterval(interval);
  }, []);

  if (!user) {
    return (
      <div className="min-h-screen bg-warm-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-warm-400 text-sm">Загрузка...</p>
        </div>
      </div>
    );
  }

  return (
    <SidebarContext.Provider value={{ collapsed }}>
      <div className="min-h-screen bg-warm-50 grain">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <CommandPalette />
        <main
          className="transition-all duration-300"
          style={{ marginLeft: collapsed ? 68 : 240 }}
        >
          <TopBar />
          {/* Active generation banner */}
          {activeJob && (
            <a
              href="/ai/generate"
              className="flex items-center gap-3 px-4 py-2.5 bg-primary/5 border-b border-primary/20 text-sm text-primary hover:bg-primary/10 transition-colors cursor-pointer"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="font-medium">Генерация курса идёт... {activeJob.progress}%</span>
              <span className="text-primary/60">{activeJob.stage}</span>
            </a>
          )}
          <div className="p-6">{children}</div>
        </main>
      </div>
    </SidebarContext.Provider>
  );
}
