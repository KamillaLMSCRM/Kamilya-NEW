'use client';

import Link from 'next/link';
import { useEffect, useState, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';

interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  plan: string;
  trial_ends_at: string | null;
  paid_until: string | null;
  max_users: number | null;
  max_courses_per_month: number | null;
  created_at: string;
}

const PLAN_KEYS = ['free', 'trial', 'pro', 'enterprise'] as const;
const STATUS_KEYS = ['active', 'trial', 'suspended', 'archived'] as const;

export default function SuperAdminTenants() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    name: '',
    slug: '',
    plan: 'trial' as typeof PLAN_KEYS[number],
    status: 'trial' as typeof STATUS_KEYS[number],
    trial_ends_at: '',
    max_users: '',
  });

  const fetchTenants = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      const res = await fetch(`${API_URL}/admin/super/tenants?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTenants(data.tenants || []);
    } catch (e) {
      toast.error(t('superadmin.tenants.loadError'));
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, search, t]);

  useEffect(() => {
    const id = setTimeout(fetchTenants, 300);
    return () => clearTimeout(id);
  }, [fetchTenants]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name,
        slug: form.slug,
        plan: form.plan,
        status: form.status,
      };
      if (form.trial_ends_at) body.trial_ends_at = new Date(form.trial_ends_at).toISOString();
      if (form.max_users) body.max_users = parseInt(form.max_users, 10);

      const res = await fetch(`${API_URL}/admin/super/tenants`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      toast.success(t('superadmin.tenants.saveOk'));
      setShowCreate(false);
      setForm({ name: '', slug: '', plan: 'trial', status: 'trial', trial_ends_at: '', max_users: '' });
      await fetchTenants();
    } catch (e) {
      toast.error(`${t('superadmin.tenants.saveError')}: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text-primary">
            {t('superadmin.tenants.title')}
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            {t('superadmin.tenants.description')}
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} variant="default">
          + {t('superadmin.tenants.create')}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <CardTitle>{t('superadmin.tenants.title')}</CardTitle>
            <Input
              type="search"
              placeholder={t('superadmin.tenants.search')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-xs"
            />
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-text-tertiary">…</p>
          ) : tenants.length === 0 ? (
            <p className="text-text-tertiary py-8 text-center">
              {t('superadmin.tenants.noTenants')}
            </p>
          ) : (
            <Table>
              <thead>
                <tr className="text-left text-xs uppercase text-text-tertiary">
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.name')}</th>
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.slug')}</th>
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.plan')}</th>
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.status')}</th>
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.users')}</th>
                  <th className="px-3 py-2">{t('superadmin.tenants.fields.created')}</th>
                  <th className="px-3 py-2 text-right">·</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tnt) => (
                  <tr key={tnt.id} className="border-t border-border">
                    <td className="px-3 py-2 font-medium">{tnt.name}</td>
                    <td className="px-3 py-2 font-mono text-xs">/{tnt.slug}</td>
                    <td className="px-3 py-2">
                      <Badge variant="secondary">{tnt.plan}</Badge>
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={tnt.status === 'active' ? 'default' : 'secondary'}>
                        {tnt.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-sm text-text-secondary">
                      {tnt.max_users ?? '∞'}
                    </td>
                    <td className="px-3 py-2 text-xs text-text-tertiary">
                      {new Date(tnt.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link href={`/admin/super/tenants/${tnt.id}`}>
                        <Button size="sm" variant="secondary">
                          {t('superadmin.tenants.edit')} →
                        </Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal
        open={showCreate}
        onClose={() => !submitting && setShowCreate(false)}
        title={t('superadmin.tenants.createTitle')}
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('superadmin.tenants.fields.name')}
            </label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              minLength={2}
              maxLength={200}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('superadmin.tenants.fields.slug')}
            </label>
            <Input
              value={form.slug}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              required
              minLength={2}
              maxLength={64}
              pattern="[a-z0-9-]+"
              placeholder="my-org"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.plan')}
              </label>
              <select
                className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm"
                value={form.plan}
                onChange={(e) => setForm({ ...form, plan: e.target.value as any })}
              >
                {PLAN_KEYS.map((p) => (
                  <option key={p} value={p}>
                    {t(`superadmin.plans.${p}`)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.status')}
              </label>
              <select
                className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm"
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value as any })}
              >
                {STATUS_KEYS.map((s) => (
                  <option key={s} value={s}>
                    {t(`superadmin.statuses.${s}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.trialEndsAt')}
              </label>
              <Input
                type="date"
                value={form.trial_ends_at}
                onChange={(e) => setForm({ ...form, trial_ends_at: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.maxUsers')}
              </label>
              <Input
                type="number"
                min="1"
                value={form.max_users}
                onChange={(e) => setForm({ ...form, max_users: e.target.value })}
                placeholder={t('superadmin.tenants.subscription.unlimited')}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setShowCreate(false)} disabled={submitting}>
              {t('superadmin.tenants.cancel')}
            </Button>
            <Button type="submit" variant="default" disabled={submitting}>
              {submitting ? '…' : t('superadmin.tenants.save')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}