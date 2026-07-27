'use client';

import Link from 'next/link';
import { Card, CardContent } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Building2, Award, Monitor, SlidersHorizontal, Users } from 'lucide-react';

export default function SettingsPage() {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const links = [
    { href: '/admin/team', label: t('nav.userManagement'), icon: Users },
    { href: '/admin/kiosks', label: t('nav.kiosks'), icon: Monitor },
    { href: '/admin/settings/integrations', label: t('integrations.title'), icon: SlidersHorizontal },
    { href: '/admin/certificates/settings', label: t('sidebar.certificateTemplate'), icon: Award },
  ];

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-foreground font-display">{t('settings.title')}</h1>
      <Card>
        <CardContent className="space-y-4 p-6">
          <div className="flex items-start gap-3">
            <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-foreground">{user?.tenant?.name || t('settings.title')}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{user?.tenant?.slug || ''}</p>
            </div>
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.security')}</p>
        </CardContent>
      </Card>

      <section aria-labelledby="tenant-settings-links" className="space-y-3">
        <h2 id="tenant-settings-links" className="text-lg font-semibold text-foreground">{t('settings.title')}</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {links.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="flex min-h-16 items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-sm font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-muted">
              <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <span>{label}</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
