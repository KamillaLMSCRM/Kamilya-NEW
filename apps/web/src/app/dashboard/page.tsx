'use client';

import Link from 'next/link';
import { Building2, Settings2, Users, type LucideIcon } from 'lucide-react';
import { OnboardingChecklist } from '@/components/admin/OnboardingChecklist';
import { MethodologistDashboard } from '@/features/dashboard/MethodologistDashboard';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';

export default function DashboardPage() {
  const user = useAuthStore((state) => state.user);
  const { t } = useT();
  const isMethodologist = user?.role === 'methodologist';

  return <div className="space-y-6">
    {isMethodologist ? <><MethodologistDashboard /><OnboardingChecklist /></> : <><OnboardingChecklist /><section className="space-y-5">
      <div><h1 className="text-2xl font-bold text-foreground font-display">{t('dashboard.title')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('onboarding.adminSubtitle')}</p></div>
      <div className="grid gap-4 md:grid-cols-3">
        <AdminLink href="/staff" label={t('nav.userManagement')} icon={Users} />
        <AdminLink href="/staff" label={t('nav.staffTree')} icon={Building2} />
        <AdminLink href="/settings" label={t('nav.settings')} icon={Settings2} />
      </div>
    </section></>}
  </div>;
}

function AdminLink({ href, label, icon: Icon }: { href: string; label: string; icon: LucideIcon }) {
  return <Link href={href} className="flex items-center gap-3 rounded-2xl border border-border bg-card p-5 font-medium text-foreground shadow-card transition hover:border-primary/50 hover:bg-primary/5"><span className="rounded-xl bg-primary/10 p-2.5 text-primary"><Icon className="h-5 w-5" /></span>{label}</Link>;
}
