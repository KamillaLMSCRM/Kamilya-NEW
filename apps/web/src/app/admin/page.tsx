'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Award,
  ChevronRight,
  Monitor,
  Settings,
  SlidersHorizontal,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { Badge, Card, CardContent, CardHeader, CardTitle, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT, type TranslationKey } from '@/i18n/useT';
import { getNavigationRoutes } from '@/lib/routeRegistry';

interface UserItem {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}

interface TrialUsageItem {
  used: number;
  limit: number | null;
  remaining: number | null;
}

interface TrialUsage {
  plan: string;
  status: string;
  trial_ends_at: string | null;
  days_left: number | null;
  ai_courses: TrialUsageItem;
  jd_courses: TrialUsageItem;
  learners: TrialUsageItem;
  system_users: TrialUsageItem;
}

const ADMIN_ACTION_IDS = new Set([
  'team',
  'tenant-settings',
  'kiosks',
  'integrations',
  'certificate-settings',
]);

const ACTION_ICONS: Record<string, LucideIcon> = {
  team: Users,
  'tenant-settings': Settings,
  kiosks: Monitor,
  integrations: SlidersHorizontal,
  'certificate-settings': Award,
};

export default function AdminDashboardPage() {
  const { t, lang } = useT();
  const token = useAuthStore((state) => state.accessToken);
  const role = useAuthStore((state) => state.user?.role);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [trialUsage, setTrialUsage] = useState<TrialUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const [usersResponse, trialUsageResponse] = await Promise.all([
        fetch(`${apiUrl}/v1/users?per_page=5`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${apiUrl}/v1/admin/trial-usage`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (usersResponse.ok) {
        const data = await usersResponse.json();
        setUsers(data.users || []);
      }
      if (trialUsageResponse.ok) setTrialUsage(await trialUsageResponse.json());
    } finally {
      setLoading(false);
    }
  }, [apiUrl, token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const quickActions = useMemo(
    () => getNavigationRoutes(role, 'sidebar').filter(({ id }) => ADMIN_ACTION_IDS.has(id)),
    [role],
  );

  const formatLimit = (item: TrialUsageItem) => (
    item.limit == null ? `${item.used} / ${t('admin.trial.unlimited')}` : `${item.used} / ${item.limit}`
  );

  const trialItems = trialUsage ? [
    { label: t('admin.trial.aiCourse'), value: formatLimit(trialUsage.ai_courses), left: trialUsage.ai_courses.remaining },
    { label: t('admin.trial.jdCourse'), value: formatLimit(trialUsage.jd_courses), left: trialUsage.jd_courses.remaining },
    { label: t('admin.trial.learners'), value: formatLimit(trialUsage.learners), left: trialUsage.learners.remaining },
    { label: t('admin.trial.systemUsers'), value: formatLimit(trialUsage.system_users), left: trialUsage.system_users.remaining },
  ] : [];

  const formatDate = (value: string) => new Date(value).toLocaleDateString(
    lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-US' : 'ru-RU',
  );

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">{t('common.loading')}</div>;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('admin.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('admin.subtitle')}</p>
      </div>

      {trialUsage && (
        <Card>
          <CardContent className="p-4 sm:p-5">
            <div className="flex flex-col gap-5">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={trialUsage.status === 'trial' ? 'secondary' : 'outline'}>
                    {trialUsage.plan}
                  </Badge>
                  <h2 className="text-lg font-semibold text-foreground">{t('admin.trial.title')}</h2>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {trialUsage.trial_ends_at
                    ? t('admin.trial.daysRemaining', {
                      days: trialUsage.days_left ?? 0,
                      date: formatDate(trialUsage.trial_ends_at),
                    })
                    : t('admin.trial.endDateMissing')}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {trialItems.map((item) => (
                  <div key={item.label} className="rounded-xl border border-border bg-muted/30 p-3">
                    <div className="text-xs text-muted-foreground">{item.label}</div>
                    <div className="mt-1 text-base font-semibold text-foreground">{item.value}</div>
                    {item.left != null && (
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {t('admin.trial.remaining')}: {item.left}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <section aria-labelledby="admin-quick-actions">
        <h2 id="admin-quick-actions" className="mb-3 text-lg font-semibold text-foreground">
          {t('admin.quickActions')}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {quickActions.map((route) => {
            const Icon = ACTION_ICONS[route.id];
            return (
              <Link
                key={route.id}
                href={route.href}
                className="group flex min-h-24 items-center gap-4 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-muted/30"
              >
                {Icon && (
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                )}
                <span className="min-w-0 flex-1 font-medium text-foreground">
                  {t(route.labelKey!)}
                </span>
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            );
          })}
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t('admin.systemTeam')}</CardTitle>
          <p className="text-sm text-muted-foreground">{t('admin.systemTeamDescription')}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          {users.length > 0 ? (
            <div className="overflow-x-auto rounded-xl border border-border">
              <Table>
                <thead>
                  <tr>
                    <th className="p-3 text-left">{t('users.name')}</th>
                    <th className="p-3 text-left">{t('users.email')}</th>
                    <th className="p-3 text-left">{t('users.role')}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} className="border-t border-border">
                      <td className="p-3">{user.first_name} {user.last_name}</td>
                      <td className="p-3 text-muted-foreground">{user.email}</td>
                      <td className="p-3">
                        <Badge variant="outline">
                          {t(`sidebar.userRole.${user.role}` as TranslationKey)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">
              {t('admin.emptySystemTeam')}
            </p>
          )}
          <Link
            href="/admin/team"
            className="inline-flex min-h-11 items-center gap-1 rounded-lg px-1 text-sm font-medium text-primary hover:underline"
          >
            {t('admin.viewSystemTeam')}
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
