'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';

interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  plan: string;
  stats: { user_count: number; course_count: number } | null;
}

export default function SuperAdminLanding() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/v1/admin/super/tenants?limit=10`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setTenants(data.tenants || []);
      } catch (e) {
        if (!cancelled) toast.error(t('superadmin.tenants.loadError'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token, API_URL, t]);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          {t('superadmin.title')}
        </h1>
        <p className="text-sm text-text-tertiary mt-1">
          {t('superadmin.superadminOnly')}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>{t('superadmin.tenants.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {loading ? '…' : tenants.length}
            </p>
            <p className="text-sm text-text-tertiary mt-2">
              {t('superadmin.tenants.description')}
            </p>
            <Link href="/admin/super/tenants">
              <Button variant="default" className="mt-4">
                {t('superadmin.tenants.title')} →
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('providers.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-text-tertiary">
              {t('providers.description')}
            </p>
            <Link href="/admin/providers">
              <Button variant="default" className="mt-4">
                {t('providers.title')} →
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('superadmin.launch.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-text-tertiary">
              {t('superadmin.launch.subtitle')}
            </p>
            <ol className="mt-3 space-y-2 text-sm text-text-secondary list-none">
              <li className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                <span>{t('superadmin.launch.steps.1')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                <span>{t('superadmin.launch.steps.2')}</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                <span>{t('superadmin.launch.steps.3')}</span>
              </li>
            </ol>
            <Link href="/admin/super/tenants">
              <Button variant="secondary" className="mt-4">
                {t('superadmin.launch.openTenants')}
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      {tenants.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('superadmin.tenants.title')} (top 10)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {tenants.slice(0, 10).map((tnt) => (
                <Link
                  key={tnt.id}
                  href={`/admin/super/tenants/${tnt.id}`}
                  className="flex items-center justify-between p-3 rounded hover:bg-bg-secondary border border-border"
                >
                  <div>
                    <div className="font-medium">{tnt.name}</div>
                    <div className="text-xs text-text-tertiary">
                      /{tnt.slug}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{tnt.plan}</Badge>
                    <Badge
                      variant={
                        tnt.status === 'active' || tnt.status === 'trial'
                          ? 'default'
                          : 'secondary'
                      }
                    >
                      {tnt.status}
                    </Badge>
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
