'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

/**
 * Root page (`/`) — редиректит в зависимости от auth-статуса:
 * - залогинен → /dashboard
 * - не залогинен → /login
 *
 * LandingPage.tsx больше не используется, файл оставлен на случай rollback.
 */
export default function Home() {
  const router = useRouter();
  const { t } = useT();
  const { user, initialize } = useAuthStore();

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    // После initialize() user либо заполнится, либо останется null
    if (user) {
      router.replace('/dashboard');
    } else {
      router.replace('/login');
    }
  }, [user, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-warm-50">
      <div className="flex flex-col items-center gap-3">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent"
          aria-label={t('common.loading')}
        />
        <p className="text-warm-400 text-sm">{t('common.loading')}</p>
      </div>
    </div>
  );
}
