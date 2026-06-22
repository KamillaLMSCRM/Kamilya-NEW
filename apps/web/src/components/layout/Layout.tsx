'use client';

import { useEffect, useState, createContext, useContext } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import CommandPalette from '@/components/CommandPalette';

const SidebarContext = createContext({ collapsed: false });

export function useSidebarCollapsed() {
  return useContext(SidebarContext);
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, initialize } = useAuthStore();
  const [collapsed, setCollapsed] = useState(false);

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
          <div className="p-6">{children}</div>
        </main>
      </div>
    </SidebarContext.Provider>
  );
}
