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
  trial_started_at: string | null;
  trial_ends_at: string | null;
  paid_until: string | null;
  max_users: number | null;
  max_courses_per_month: number | null;
  billing_contact_email: string | null;
  billing_company_name: string | null;
  billing_identifier: string | null;
  created_at: string;
  stats?: {
    user_count: number;
    active_user_count: number;
    admin_count: number;
    course_count: number;
    published_course_count: number;
    document_count: number;
    enrollment_count: number;
    last_activity_at: string | null;
  } | null;
  usage?: {
    ai_course_generations_used: number;
    jd_course_generations_used: number;
    active_students_count_snapshot: number;
    system_users_count_snapshot: number;
    updated_at: string | null;
  } | null;
  latest_lead?: {
    contact_name: string;
    email: string;
    phone: string | null;
    telegram_username: string | null;
    employee_count_range: string | null;
    intent: string;
    status: string;
    created_at: string;
  } | null;
}

const PLAN_KEYS = ['free', 'trial', 'pro', 'enterprise'] as const;
const STATUS_KEYS = ['active', 'trial', 'suspended', 'archived'] as const;
const SLUG_PATTERN = /^[a-z0-9-]+$/;
const CYRILLIC_TO_LATIN: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  е: 'e',
  ё: 'e',
  ж: 'zh',
  з: 'z',
  и: 'i',
  й: 'i',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'h',
  ц: 'ts',
  ч: 'ch',
  ш: 'sh',
  щ: 'sch',
  ъ: '',
  ы: 'y',
  і: 'i',
  ь: '',
  э: 'e',
  ю: 'yu',
  я: 'ya',
  ә: 'a',
  ғ: 'g',
  қ: 'k',
  ң: 'n',
  ө: 'o',
  ұ: 'u',
  ү: 'u',
  һ: 'h',
};

function slugifyTenantName(value: string) {
  const transliterated = value
    .trim()
    .toLowerCase()
    .split('')
    .map((char) => CYRILLIC_TO_LATIN[char] ?? char)
    .join('');

  return transliterated
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .replace(/-{2,}/g, '-')
    .slice(0, 64);
}

function normalizeSlug(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+/, '')
    .slice(0, 64);
}

function errorMessageFromResponse(payload: unknown) {
  if (!payload || typeof payload !== 'object') return 'Unknown';
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const record = item as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(record.loc) ? record.loc.slice(1).join('.') : '';
        return [field, record.msg].filter(Boolean).join(': ');
      })
      .filter(Boolean)
      .join('; ');
  }
  return 'Unknown';
}

function formatDate(value: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('ru-KZ', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(value));
}

function trialDaysLeft(value: string | null) {
  if (!value) return '—';
  const days = Math.ceil((new Date(value).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return `${Math.abs(days)} дн. назад`;
  return `${days} дн.`;
}

export default function SuperAdminTenants() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
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
  const [slugEdited, setSlugEdited] = useState(false);

  const fetchTenants = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setLoadFailed(false);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      const res = await fetch(`${API_URL}/v1/admin/super/tenants?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTenants(data.tenants || []);
    } catch (e) {
      setLoadFailed(true);
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
    const slug = normalizeSlug(form.slug || slugifyTenantName(form.name));
    if (!SLUG_PATTERN.test(slug) || slug.length < 2) {
      toast.error('Slug должен содержать минимум 2 символа: латинские буквы, цифры и дефисы.');
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        slug,
        plan: form.plan,
        status: form.status,
      };
      if (form.trial_ends_at) body.trial_ends_at = new Date(form.trial_ends_at).toISOString();
      if (form.max_users) body.max_users = parseInt(form.max_users, 10);

      const res = await fetch(`${API_URL}/v1/admin/super/tenants`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown' }));
        throw new Error(errorMessageFromResponse(err) || `HTTP ${res.status}`);
      }
      toast.success(t('superadmin.tenants.saveOk'));
      setShowCreate(false);
      setForm({ name: '', slug: '', plan: 'trial', status: 'trial', trial_ends_at: '', max_users: '' });
      setSlugEdited(false);
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
          {loadFailed ? (
            <div className="rounded border border-destructive/30 bg-destructive/5 p-4 text-sm">
              <p className="text-text-primary">{t('superadmin.tenants.loadError')}</p>
              <Button size="sm" variant="secondary" className="mt-3" onClick={fetchTenants}>
                {t('common.retry')}
              </Button>
            </div>
          ) : loading ? (
            <p className="text-text-tertiary py-8 text-center">
              {t('common.loading')}
            </p>
          ) : tenants.length === 0 ? (
            <div className="py-10 text-center">
              <p className="text-text-tertiary">{t('superadmin.tenants.noTenants')}</p>
              <Button
                size="sm"
                variant="default"
                className="mt-4"
                onClick={() => setShowCreate(true)}
              >
                {t('superadmin.tenants.createFirst')}
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <thead>
                  <tr className="text-left text-xs uppercase text-text-tertiary">
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.name')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.contact')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.planStatus')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.trial')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.users')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.aiUsage')}</th>
                    <th className="px-3 py-2">{t('superadmin.tenants.fields.activity')}</th>
                    <th className="px-3 py-2 text-right">·</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((tnt) => (
                    <tr key={tnt.id} className="border-t border-border">
                      <td className="px-3 py-2">
                        <div className="font-medium text-text-primary">{tnt.name}</div>
                        <div className="text-xs font-mono text-text-tertiary">/{tnt.slug}</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-sm text-text-primary">
                          {tnt.latest_lead?.contact_name || '—'}
                        </div>
                        <div className="text-xs text-text-tertiary break-all">
                          {tnt.billing_contact_email || tnt.latest_lead?.email || '—'}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          <Badge variant="secondary">{t(`superadmin.plans.${tnt.plan}` as any)}</Badge>
                          <Badge variant={tnt.status === 'active' ? 'default' : 'secondary'}>
                            {t(`superadmin.statuses.${tnt.status}` as any)}
                          </Badge>
                        </div>
                        <div className="mt-1 text-xs text-text-tertiary">
                          {tnt.latest_lead?.intent
                            ? t('superadmin.tenants.source.lead', { intent: tnt.latest_lead.intent })
                            : t('superadmin.tenants.source.manual')}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-sm text-text-secondary">
                        <div className="font-medium text-text-primary">{trialDaysLeft(tnt.trial_ends_at)}</div>
                        <div className="text-xs text-text-tertiary">
                          {t('superadmin.tenants.trialUntil', { date: formatDate(tnt.trial_ends_at) })}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-sm text-text-secondary">
                        <div className="font-medium text-text-primary">
                          {tnt.stats?.active_user_count ?? 0}/{tnt.stats?.user_count ?? 0}
                        </div>
                        <div className="text-xs text-text-tertiary">
                          {t('superadmin.tenants.subscription.maxUsers')}: {tnt.max_users ?? '∞'}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-sm text-text-secondary">
                        <div className="font-medium text-text-primary">
                          {t('superadmin.tenants.launch.aiCourses')} {tnt.usage?.ai_course_generations_used ?? 0}/1 · {t('superadmin.tenants.launch.jdCourses')} {tnt.usage?.jd_course_generations_used ?? 0}/1
                        </div>
                        <div className="text-xs text-text-tertiary">
                          {t('superadmin.tenants.publishedOfTotal', {
                            published: tnt.stats?.published_course_count ?? 0,
                            total: tnt.stats?.course_count ?? 0,
                          })}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-text-tertiary">
                        <div>{t('superadmin.tenants.activity.created', { date: formatDate(tnt.created_at) })}</div>
                        <div>{t('superadmin.tenants.activity.lastLogin', { date: formatDate(tnt.stats?.last_activity_at ?? null) })}</div>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Link href={`/admin/super/tenants/${tnt.id}`}>
                          <Button size="sm" variant="secondary">
                            {t('superadmin.tenants.open')}
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
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
              onChange={(e) => {
                const name = e.target.value;
                setForm({
                  ...form,
                  name,
                  slug: slugEdited ? form.slug : slugifyTenantName(name),
                });
              }}
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
              onChange={(e) => {
                setSlugEdited(true);
                setForm({ ...form, slug: normalizeSlug(e.target.value) });
              }}
              required
              minLength={2}
              maxLength={64}
              placeholder="my-org"
              inputMode="url"
            />
            <p className="mt-1 text-xs text-text-tertiary">
              Только латинские буквы, цифры и дефисы. Заполняется автоматически из названия.
            </p>
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
