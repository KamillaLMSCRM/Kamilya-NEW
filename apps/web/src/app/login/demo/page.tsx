'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuthStore } from '@/store/authStore';
import { clearStoredAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { PublicWorkspace, WorkspacePanel } from '@/features/workspace-design';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PUBLIC_DEMO_ROLE_IDS } from '@/lib/demoRoleCopy';
import { useT } from '@/i18n/useT';
import { useLocaleQuery } from '@/i18n/useLocaleQuery';
import { BookOpen, GraduationCap, ArrowLeft, ChevronRight } from 'lucide-react';

interface RoleCard {
  role: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
  redirect: string;
}

export default function DemoLoginPage() {
  useLocaleQuery();
  const router = useRouter();
  const { t, lang } = useT();
  const { login } = useAuthStore();
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState('');
  const roles: RoleCard[] = [
    {
      role: PUBLIC_DEMO_ROLE_IDS[0],
      title: t('users.roleMethodologist'),
      description: t('demo.login.methodologistDescription'),
      icon: <BookOpen className="w-8 h-8" />,
      color: 'text-success',
      bg: 'bg-success/10 hover:bg-success/15 border-success/30',
      redirect: '/courses',
    },
    {
      role: PUBLIC_DEMO_ROLE_IDS[1],
      title: t('users.roleStudent'),
      description: t('demo.login.studentDescription'),
      icon: <GraduationCap className="w-8 h-8" />,
      color: 'text-accent',
      bg: 'bg-accent/10 hover:bg-accent/15 border-accent/30',
      redirect: '/my-courses',
    },
  ];

  const handleDemoLogin = async (card: RoleCard) => {
    setLoading(card.role);
    setError('');
    try {
      clearStoredAuth();
      const res = await api.post('/v1/auth/demo-login', { role: card.role });
      login(res.data.access_token, res.data.user);
      router.push(card.redirect);
    } catch (err: any) {
      setError(err.response?.data?.detail || t('demo.login.error'));
    } finally {
      setLoading(null);
    }
  };

  return (
    <PublicWorkspace id="demo-login" title={t('demo.login.title')} description={t('demo.login.exampleSubtitle')} actions={<LanguageSwitcher />}>

        {error && (
          <div className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm" role="alert">
            {error}
          </div>
        )}

        <Link
          href={`/login/example?lang=${lang}`}
          className="flex min-w-0 items-center justify-between gap-4 rounded-2xl border border-primary/20 bg-card p-5 text-left transition-colors hover:bg-primary/5"
        >
          <span>
            <span className="block font-semibold text-foreground">{t('demo.login.openExample')}</span>
            <span className="mt-1 block text-sm text-muted-foreground">{t('demo.login.exampleDescription')}</span>
          </span>
          <ChevronRight className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
        </Link>

        <WorkspacePanel title={t('demo.login.workspaceSubtitle')}>
        <div className="grid min-w-0 gap-4 md:grid-cols-2">
          {roles.map((card) => (
            <button
              key={card.role}
              onClick={() => handleDemoLogin(card)}
              disabled={loading !== null}
              className={`flex min-w-0 items-start gap-4 rounded-2xl border p-5 text-left transition-colors ${card.bg} ${loading === card.role ? 'opacity-60 cursor-wait' : 'cursor-pointer'}`}
            >
              <div className={`shrink-0 ${card.color}`}>
                {loading === card.role ? (
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-current" />
                ) : (
                  card.icon
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-foreground text-lg">{card.title}</div>
                <div className="text-sm text-muted-foreground mt-0.5">{card.description}</div>
              </div>
              <svg className="w-5 h-5 text-muted-foreground/60 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
        </WorkspacePanel>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 border-t border-border pt-6 text-center">
          <Link
            href={`/login?lang=${lang}`}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('demo.login.back')}
          </Link>
          <Link
            href={`/register-tenant?lang=${lang}`}
            className="text-sm font-medium text-primary hover:underline"
          >
            {t('demo.login.register')}
          </Link>
        </div>
    </PublicWorkspace>
  );
}
