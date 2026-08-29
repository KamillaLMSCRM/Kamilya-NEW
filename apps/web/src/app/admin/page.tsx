'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Award,
  ChevronRight,
  History,
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
import { OnboardingChecklist } from '@/components/admin/OnboardingChecklist';

interface UserItem {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}

const ADMIN_ACTION_IDS = new Set([
  'team',
  'tenant-settings',
  'kiosks',
  'integrations',
  'certificate-settings',
  'audit-log',
]);

const ACTION_ICONS: Record<string, LucideIcon> = {
  team: Users,
  'tenant-settings': Settings,
  kiosks: Monitor,
  integrations: SlidersHorizontal,
  'certificate-settings': Award,
  'audit-log': History,
};

export default function AdminDashboardPage() {
  const { t } = useT();
  const token = useAuthStore((state) => state.accessToken);
  const role = useAuthStore((state) => state.user?.role);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const usersResponse = await fetch(`${apiUrl}/v1/users?per_page=5`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (usersResponse.ok) {
        const data = await usersResponse.json();
        setUsers(data.users || []);
      }
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

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">{t('common.loading')}</div>;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('admin.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('admin.subtitle')}</p>
      </div>

      <OnboardingChecklist />

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
