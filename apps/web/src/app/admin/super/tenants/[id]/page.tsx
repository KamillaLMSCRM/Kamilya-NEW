'use client';

import Link from 'next/link';
import { useEffect, useState, useCallback, use } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';

const PLAN_KEYS = ['free', 'trial', 'pro', 'enterprise'] as const;
const STATUS_KEYS = ['active', 'trial', 'suspended', 'archived'] as const;
const ROLE_KEYS = ['admin', 'org_admin', 'teacher'] as const;

interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  plan: string;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  paid_until: string | null;
  max_users: number | null;
  max_courses_per_month: number | null;
  billing_contact_email: string | null;
  billing_company_name: string | null;
  billing_identifier: string | null;
  notes: string | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  stats?: {
    user_count: number;
    active_user_count: number;
    admin_count: number;
    course_count: number;
    published_course_count: number;
    document_count: number;
    enrollment_count: number;
    last_activity_at: string | null;
  };
  usage?: {
    ai_course_generations_used: number;
    jd_course_generations_used: number;
    active_students_count_snapshot: number;
    system_users_count_snapshot: number;
    updated_at: string | null;
  } | null;
  latest_lead?: {
    id: string;
    company_name: string;
    contact_name: string;
    email: string;
    phone: string | null;
    telegram_username: string | null;
    employee_count_range: string | null;
    intent: string;
    status: string;
    source: string;
    message: string | null;
    created_at: string;
  } | null;
}

interface Admin {
  id: string;
  email: string | null;
  telegram_id: number | null;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  last_login: string | null;
  created_at: string;
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('ru-KZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(value));
}

function addDaysIso(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  date.setHours(23, 59, 59, 0);
  return date.toISOString();
}

export default function TenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const router = useRouter();

  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);

  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const [showAddAdmin, setShowAddAdmin] = useState(false);
  const [adminForm, setAdminForm] = useState({
    email: '',
    telegram_id: '',
    first_name: '',
    last_name: '',
    role: 'admin' as typeof ROLE_KEYS[number],
    send_invite: false,
  });
  const [addingAdmin, setAddingAdmin] = useState(false);

  const [impersonateRole, setImpersonateRole] = useState<'admin' | 'org_admin' | 'teacher'>('admin');
  const [impersonating, setImpersonating] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setLoadFailed(false);
    try {
      const [tRes, aRes] = await Promise.all([
        fetch(`${API_URL}/v1/admin/super/tenants/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_URL}/v1/admin/super/tenants/${id}/admins`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);
      if (!tRes.ok) throw new Error(`HTTP ${tRes.status}`);
      const tnt = await tRes.json();
      setTenant(tnt);
      setEditForm({
        name: tnt.name,
        slug: tnt.slug,
        status: tnt.status,
        plan: tnt.plan,
        trial_ends_at: tnt.trial_ends_at ? tnt.trial_ends_at.slice(0, 10) : '',
        paid_until: tnt.paid_until ? tnt.paid_until.slice(0, 10) : '',
        max_users: tnt.max_users != null ? String(tnt.max_users) : '',
        max_courses_per_month: tnt.max_courses_per_month != null ? String(tnt.max_courses_per_month) : '',
        notes: tnt.notes || '',
      });
      if (aRes.ok) {
        const data = await aRes.json();
        setAdmins(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      setLoadFailed(true);
      toast.error(t('superadmin.tenants.loadError'));
    } finally {
      setLoading(false);
    }
  }, [id, token, API_URL, t]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const patchTenant = async (body: Record<string, unknown>) => {
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/v1/admin/super/tenants/${id}`, {
        method: 'PATCH',
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
      await fetchAll();
    } catch (e) {
      toast.error(`${t('superadmin.tenants.saveError')}: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    if (!tenant) return;
    const body: Record<string, unknown> = {};
    const fields = ['name', 'slug', 'status', 'plan', 'trial_ends_at', 'paid_until', 'max_users', 'max_courses_per_month', 'notes'];
    for (const f of fields) {
      const v = editForm[f];
      if (v === undefined) continue;
      if (v === '') {
        if (f === 'trial_ends_at' || f === 'paid_until' || f === 'max_users' || f === 'max_courses_per_month') {
          body[f] = null;
        } else {
          body[f] = v;
        }
      } else if (f === 'max_users' || f === 'max_courses_per_month') {
        body[f] = parseInt(v, 10);
      } else if (f === 'trial_ends_at' || f === 'paid_until') {
        body[f] = new Date(v).toISOString();
      } else {
        body[f] = v;
      }
    }
    await patchTenant(body);
  };

  const handleAddAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminForm.email && !adminForm.telegram_id) {
      toast.error(t('superadmin.admins.identifierRequired'));
      return;
    }
    setAddingAdmin(true);
    try {
      const body: Record<string, unknown> = {
        first_name: adminForm.first_name,
        last_name: adminForm.last_name,
        role: adminForm.role,
      };
      if (adminForm.email) body.email = adminForm.email;
      if (adminForm.telegram_id) body.telegram_id = parseInt(adminForm.telegram_id, 10);
      if (adminForm.send_invite && adminForm.email) body.send_invite = true;

      const res = await fetch(`${API_URL}/v1/admin/super/tenants/${id}/admins`, {
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
      toast.success(t('superadmin.admins.saveOk'));
      setShowAddAdmin(false);
      setAdminForm({ email: '', telegram_id: '', first_name: '', last_name: '', role: 'admin', send_invite: false });
      await fetchAll();
    } catch (e) {
      toast.error(`${t('superadmin.admins.saveError')}: ${(e as Error).message}`);
    } finally {
      setAddingAdmin(false);
    }
  };

  const handleDeactivate = async (admin: Admin) => {
    if (!confirm(t('superadmin.admins.deactivateConfirm', { name: `${admin.first_name} ${admin.last_name}` }))) return;
    try {
      const res = await fetch(`${API_URL}/v1/admin/super/tenants/${id}/admins/${admin.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(t('superadmin.admins.deactivateOk'));
      await fetchAll();
    } catch (e) {
      toast.error(t('superadmin.admins.deactivateError'));
    }
  };

  const handleImpersonate = async () => {
    if (!token) return;
    setImpersonating(true);
    try {
      const res = await fetch(`${API_URL}/v1/admin/super/tenants/${id}/impersonate`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ role: impersonateRole }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      // Replace AuthStore with the impersonation session so the next
      // navigation picks up the new token + user payload.
      const { useAuthStore } = await import('@/store/authStore');
      useAuthStore.getState().login(data.access_token, data.user);
      toast.success(
        t('superadmin.tenants.impersonate.entering', {
          name: data.tenant.name,
          role: data.as_role,
        })
      );
      router.push('/dashboard');
    } catch (e) {
      toast.error(t('superadmin.tenants.impersonate.error', { error: (e as Error).message }));
    } finally {
      setImpersonating(false);
    }
  };

  if (loading) return <div className="p-6 text-text-tertiary">{t('common.loading')}</div>;
  if (loadFailed) {
    return (
      <div className="p-6">
        <div className="rounded border border-destructive/30 bg-destructive/5 p-4 text-sm max-w-xl">
          <p className="text-text-primary">{t('superadmin.tenants.loadError')}</p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={fetchAll}>
            {t('common.retry')}
          </Button>
        </div>
      </div>
    );
  }
  if (!tenant) return <div className="p-6 text-red-600">{t('superadmin.tenants.notFound')}</div>;

  const stats = tenant.stats;
  const usage = tenant.usage;
  const lead = tenant.latest_lead;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/admin/super/tenants" className="text-text-tertiary hover:text-text-primary">
          ←
        </Link>
        <h1 className="text-2xl font-semibold">{tenant.name}</h1>
        <Badge variant="secondary">{t(`superadmin.plans.${tenant.plan}` as any)}</Badge>
        <Badge variant={tenant.status === 'active' ? 'default' : 'secondary'}>
          {t(`superadmin.statuses.${tenant.status}` as any)}
        </Badge>
        <code className="text-xs text-text-tertiary">/{tenant.slug}</code>

        {/* Impersonation control — superadmin enters the tenant as
            one of its admin-level roles. Useful for debugging what
            a real tenant user sees, and for support. */}
        <div className="ml-auto flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3 py-1.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="text-warning shrink-0">
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M22 11h-6" />
            <path d="m19 8-3 3 3 3" />
          </svg>
          <span className="text-xs text-warning/90 font-medium">{t('superadmin.tenants.impersonate.label')}</span>
          <select
            value={impersonateRole}
            onChange={(e) => setImpersonateRole(e.target.value as typeof impersonateRole)}
            className="rounded border border-warning/30 bg-background px-2 py-1 text-xs"
            disabled={impersonating}
          >
            {ROLE_KEYS.map((r) => (
              <option key={r} value={r}>
                {t(`superadmin.roles.${r}`)}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="default"
            onClick={handleImpersonate}
            disabled={impersonating}
            className="bg-warning text-warning-foreground hover:bg-warning/90"
          >
            {impersonating ? t('common.loading') : t('superadmin.tenants.impersonate.submit')}
          </Button>
        </div>
      </div>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader>
          <CardTitle>Панель запуска</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr_1fr]">
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-text-tertiary">
                {t('superadmin.tenants.launch.contact')}
              </div>
              <div className="text-sm font-medium">{lead?.contact_name || '—'}</div>
              <div className="break-all text-sm text-text-secondary">
                {tenant.billing_contact_email || lead?.email || '—'}
              </div>
              <div className="text-xs text-text-tertiary">
                {lead?.phone || t('superadmin.tenants.lead.phoneMissing')} ·{' '}
                {lead?.telegram_username || t('superadmin.tenants.lead.telegramMissing')}
              </div>
              {lead?.message && (
                <div className="rounded border border-border bg-bg-primary p-2 text-xs text-text-secondary">
                  {lead.message}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-text-tertiary">
                {t('superadmin.tenants.launch.usage')}
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded border border-border bg-bg-primary p-2">
                  <div className="text-text-tertiary text-xs">
                    {t('superadmin.tenants.launch.aiCourses')}
                  </div>
                  <div className="font-semibold">{usage?.ai_course_generations_used ?? 0}/1</div>
                </div>
                <div className="rounded border border-border bg-bg-primary p-2">
                  <div className="text-text-tertiary text-xs">
                    {t('superadmin.tenants.launch.jdCourses')}
                  </div>
                  <div className="font-semibold">{usage?.jd_course_generations_used ?? 0}/1</div>
                </div>
                <div className="rounded border border-border bg-bg-primary p-2">
                  <div className="text-text-tertiary text-xs">
                    {t('superadmin.tenants.launch.learners')}
                  </div>
                  <div className="font-semibold">
                    {usage?.active_students_count_snapshot ?? stats?.active_user_count ?? 0}/{tenant.max_users ?? 10}
                  </div>
                </div>
                <div className="rounded border border-border bg-bg-primary p-2">
                  <div className="text-text-tertiary text-xs">
                    {t('superadmin.tenants.launch.team')}
                  </div>
                  <div className="font-semibold">{usage?.system_users_count_snapshot ?? stats?.admin_count ?? 0}/3</div>
                </div>
              </div>
              <div className="text-xs text-text-tertiary">
                {t('superadmin.tenants.launch.updatedAt', { date: formatDate(usage?.updated_at) })}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-text-tertiary">
                {t('superadmin.tenants.launch.actions')}
              </div>
              <Button
                type="button"
                className="w-full"
                disabled={saving}
                onClick={() => patchTenant({ plan: 'pro', status: 'active', paid_until: addDaysIso(30) })}
              >
                {t('superadmin.tenants.launch.activatePaid', { days: 30 })}
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                disabled={saving}
                onClick={() => patchTenant({ status: 'trial', plan: 'trial', trial_ends_at: addDaysIso(14) })}
              >
                {t('superadmin.tenants.launch.extendTrial', { days: 14 })}
              </Button>
              <Button
                type="button"
                variant="destructive"
                className="w-full"
                disabled={saving}
                onClick={() => patchTenant({ status: 'suspended' })}
              >
                {t('superadmin.tenants.launch.suspend')}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-tertiary">{t('superadmin.tenants.stats.users')}</p>
            <p className="text-2xl font-semibold">{stats?.user_count ?? 0}</p>
            <p className="text-xs text-text-tertiary">
              {stats?.active_user_count ?? 0} {t('superadmin.tenants.stats.activeUsers')}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-tertiary">{t('superadmin.tenants.stats.admins')}</p>
            <p className="text-2xl font-semibold">{stats?.admin_count ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-tertiary">{t('superadmin.tenants.stats.courses')}</p>
            <p className="text-2xl font-semibold">{stats?.course_count ?? 0}</p>
            <p className="text-xs text-text-tertiary">
              {stats?.published_course_count ?? 0} {t('superadmin.tenants.stats.published')}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-text-tertiary">{t('superadmin.tenants.stats.enrollments')}</p>
            <p className="text-2xl font-semibold">{stats?.enrollment_count ?? 0}</p>
            <p className="text-xs text-text-tertiary">
              {t('superadmin.tenants.stats.lastActivity')}: {stats?.last_activity_at
                ? new Date(stats.last_activity_at).toLocaleDateString()
                : t('superadmin.tenants.stats.never')}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Subscription edit */}
      <Card>
        <CardHeader>
          <CardTitle>{t('superadmin.tenants.subscription.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.fields.name')}
              </label>
              <Input
                value={editForm.name || ''}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.fields.slug')}
              </label>
              <Input
                value={editForm.slug || ''}
                onChange={(e) => setEditForm({ ...editForm, slug: e.target.value })}
                pattern="[a-z0-9-]+"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.plan')}
              </label>
              <select
                className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm"
                value={editForm.plan || ''}
                onChange={(e) => setEditForm({ ...editForm, plan: e.target.value })}
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
                value={editForm.status || ''}
                onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
              >
                {STATUS_KEYS.map((s) => (
                  <option key={s} value={s}>
                    {t(`superadmin.statuses.${s}`)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.trialEndsAt')}
              </label>
              <Input
                type="date"
                value={editForm.trial_ends_at || ''}
                onChange={(e) => setEditForm({ ...editForm, trial_ends_at: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.paidUntil')}
              </label>
              <Input
                type="date"
                value={editForm.paid_until || ''}
                onChange={(e) => setEditForm({ ...editForm, paid_until: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.maxUsers')}
              </label>
              <Input
                type="number"
                min="1"
                value={editForm.max_users || ''}
                onChange={(e) => setEditForm({ ...editForm, max_users: e.target.value })}
                placeholder={t('superadmin.tenants.subscription.unlimited')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.maxCourses')}
              </label>
              <Input
                type="number"
                min="0"
                value={editForm.max_courses_per_month || ''}
                onChange={(e) => setEditForm({ ...editForm, max_courses_per_month: e.target.value })}
                placeholder={t('superadmin.tenants.subscription.unlimited')}
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.tenants.subscription.notes')}
              </label>
              <textarea
                className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm min-h-[80px]"
                value={editForm.notes || ''}
                onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                maxLength={2000}
              />
            </div>
          </div>
          <div className="flex justify-end mt-4">
            <Button onClick={handleSave} variant="default" disabled={saving}>
              {saving ? '…' : t('superadmin.tenants.save')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Admins */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t('superadmin.admins.title')}</CardTitle>
          <Button onClick={() => setShowAddAdmin(true)} variant="default">
            + {t('superadmin.admins.add')}
          </Button>
        </CardHeader>
        <CardContent>
          {admins.length === 0 ? (
            <p className="text-text-tertiary py-8 text-center">
              {t('superadmin.admins.noAdmins')}
            </p>
          ) : (
            <Table>
              <thead>
                <tr className="text-left text-xs uppercase text-text-tertiary">
                  <th className="px-3 py-2">{t('superadmin.admins.fields.name')}</th>
                  <th className="px-3 py-2">{t('superadmin.admins.fields.email')}</th>
                  <th className="px-3 py-2">{t('superadmin.admins.fields.telegram')}</th>
                  <th className="px-3 py-2">{t('superadmin.admins.fields.role')}</th>
                  <th className="px-3 py-2">{t('superadmin.admins.fields.lastLogin')}</th>
                  <th className="px-3 py-2 text-right">·</th>
                </tr>
              </thead>
              <tbody>
                {admins.map((a) => (
                  <tr key={a.id} className="border-t border-border">
                    <td className="px-3 py-2">
                      {a.first_name} {a.last_name}
                      {!a.is_active && (
                        <Badge variant="secondary" className="ml-2">
                          {t('superadmin.admins.fields.active')}: ✗
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-sm">{a.email || '—'}</td>
                    <td className="px-3 py-2 text-sm font-mono">{a.telegram_id || '—'}</td>
                    <td className="px-3 py-2">
                      <Badge variant="secondary">{a.role}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-text-tertiary">
                      {a.last_login ? new Date(a.last_login).toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {a.is_active && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDeactivate(a)}
                        >
                          {t('superadmin.admins.deactivate')}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal
        open={showAddAdmin}
        onClose={() => !addingAdmin && setShowAddAdmin(false)}
        title={t('superadmin.admins.addTitle')}
      >
        <form onSubmit={handleAddAdmin} className="space-y-4">
          <div className="text-xs text-text-tertiary -mt-2">
            {t('superadmin.admins.form.identifierHelp')}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.admins.fields.email')}
              </label>
              <Input
                type="email"
                value={adminForm.email}
                onChange={(e) => setAdminForm({ ...adminForm, email: e.target.value })}
                placeholder="admin@org.kz"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.admins.fields.telegram')}
              </label>
              <Input
                type="number"
                value={adminForm.telegram_id}
                onChange={(e) => setAdminForm({ ...adminForm, telegram_id: e.target.value })}
                placeholder="123456789"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.admins.form.firstName')}
              </label>
              <Input
                value={adminForm.first_name}
                onChange={(e) => setAdminForm({ ...adminForm, first_name: e.target.value })}
                required
                minLength={1}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">
                {t('superadmin.admins.form.lastName')}
              </label>
              <Input
                value={adminForm.last_name}
                onChange={(e) => setAdminForm({ ...adminForm, last_name: e.target.value })}
                required
                minLength={1}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('superadmin.admins.fields.role')}
            </label>
            <select
              className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm"
              value={adminForm.role}
              onChange={(e) => setAdminForm({ ...adminForm, role: e.target.value as any })}
            >
              {ROLE_KEYS.map((r) => (
                <option key={r} value={r}>
                  {t(`superadmin.roles.${r}`)}
                </option>
              ))}
            </select>
          </div>
          {adminForm.email && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={adminForm.send_invite}
                onChange={(e) => setAdminForm({ ...adminForm, send_invite: e.target.checked })}
              />
              <span>{t('superadmin.admins.form.sendInvite')}</span>
              <span className="text-text-tertiary text-xs">
                ({t('superadmin.admins.form.sendInviteHelp')})
              </span>
            </label>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setShowAddAdmin(false)} disabled={addingAdmin}>
              {t('superadmin.admins.cancel')}
            </Button>
            <Button type="submit" variant="default" disabled={addingAdmin}>
              {addingAdmin ? '…' : t('superadmin.admins.save')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
