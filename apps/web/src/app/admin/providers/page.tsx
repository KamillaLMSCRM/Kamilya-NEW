'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';

interface ProviderKey {
  id: string;
  provider: 'deepseek' | 'voyage' | 'cohere';
  label: string | null;
  is_active: boolean;
  key_preview: string;
  source: 'db' | 'env';
  created_by: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  last_error: string | null;
}

export default function AdminProvidersPage() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);

  // New-key form state
  const [newProvider, setNewProvider] = useState<'deepseek' | 'voyage' | 'cohere'>('deepseek');
  const [newApiKey, setNewApiKey] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchKeys = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/admin/provider-keys`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setKeys(data.providers || []);
    } catch (e) {
      console.error(e);
      toast.error(t('providers.loadError'));
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, t]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/admin/provider-keys`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider: newProvider,
          api_key: newApiKey,
          label: newLabel || null,
          is_active: true,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      toast.success(t('providers.saveOk'));
      setShowCreate(false);
      setNewApiKey('');
      setNewLabel('');
      await fetchKeys();
    } catch (e) {
      console.error(e);
      toast.error(`${t('providers.saveError')}: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleActive = async (key: ProviderKey) => {
    try {
      const res = await fetch(`${API_URL}/admin/provider-keys/${key.id}`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ is_active: !key.is_active }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchKeys();
    } catch (e) {
      console.error(e);
      toast.error(t('providers.saveError'));
    }
  };

  const handleDelete = async (key: ProviderKey) => {
    const label = key.label || key.provider;
    if (!confirm(t('providers.deleteConfirm', { label }))) return;
    try {
      const res = await fetch(`${API_URL}/admin/provider-keys/${key.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(t('providers.deleteOk'));
      await fetchKeys();
    } catch (e) {
      console.error(e);
      toast.error(t('providers.deleteError'));
    }
  };

  const handleTest = async (key: ProviderKey) => {
    setTestingId(key.id);
    try {
      const res = await fetch(`${API_URL}/admin/provider-keys/${key.id}/test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok) {
        toast.success(t('providers.testOk', { latency: data.latency_ms }));
      } else {
        toast.error(t('providers.testFail', { error: data.error || 'unknown' }));
      }
      await fetchKeys(); // refresh last_used_at + last_error
    } catch (e) {
      console.error(e);
      toast.error(t('providers.testFail', { error: (e as Error).message }));
    } finally {
      setTestingId(null);
    }
  };

  const providerLabel = (p: string) =>
    (t as any)(`providers.providersList.${p}`) || p;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">
          {t('providers.title')}
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          {t('providers.description')}
        </p>
        <p className="text-xs text-text-tertiary mt-2">
          {t('providers.superadminOnly')}
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t('providers.title')}</CardTitle>
          <Button onClick={() => setShowCreate(true)} variant="default">
            + {t('providers.addKey')}
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-text-tertiary">…</p>
          ) : keys.length === 0 ? (
            <p className="text-text-tertiary py-8 text-center">
              {t('providers.noKeys')}
            </p>
          ) : (
            <Table>
              <thead>
                <tr className="text-left text-xs uppercase text-text-tertiary">
                  <th className="px-3 py-2">{t('providers.provider')}</th>
                  <th className="px-3 py-2">{t('providers.label')}</th>
                  <th className="px-3 py-2">{t('providers.keyPreview')}</th>
                  <th className="px-3 py-2">{t('providers.active')}</th>
                  <th className="px-3 py-2">{t('providers.lastUsed')}</th>
                  <th className="px-3 py-2">{t('providers.lastError')}</th>
                  <th className="px-3 py-2 text-right">·</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id} className="border-t border-border">
                    <td className="px-3 py-2 font-medium">
                      {providerLabel(k.provider)}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {k.label || '—'}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {k.key_preview}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={k.is_active ? 'secondary' : 'default'}>
                        {k.is_active ? t('providers.active') : t('providers.inactive')}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-text-tertiary">
                      {k.last_used_at
                        ? new Date(k.last_used_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {k.last_error ? (
                        <span className="text-red-600">{k.last_error}</span>
                      ) : (
                        <span className="text-text-tertiary">
                          {t('providers.lastErrorNone')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-2 justify-end">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleTest(k)}
                          disabled={testingId === k.id}
                        >
                          {testingId === k.id ? t('providers.testing') : t('providers.test')}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleToggleActive(k)}
                        >
                          {k.is_active ? t('providers.deactivate') : t('providers.activate')}
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDelete(k)}
                        >
                          {t('providers.delete')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Add-key modal */}
      <Modal
        open={showCreate}
        onClose={() => !submitting && setShowCreate(false)}
        title={t('providers.addKeyTitle')}
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('providers.provider')}
            </label>
            <select
              className="w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm"
              value={newProvider}
              onChange={(e) => setNewProvider(e.target.value as 'deepseek' | 'voyage' | 'cohere')}
              disabled={submitting}
            >
              <option value="deepseek">{providerLabel('deepseek')}</option>
              <option value="voyage">{providerLabel('voyage')}</option>
              <option value="cohere">{providerLabel('cohere')}</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('providers.apiKey')}
            </label>
            <Input
              type="password"
              value={newApiKey}
              onChange={(e) => setNewApiKey(e.target.value)}
              required
              minLength={8}
              autoComplete="off"
              placeholder="sk-…"
              disabled={submitting}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              {t('providers.label')}
            </label>
            <Input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              maxLength={128}
              placeholder={t('providers.labelPlaceholder')}
              disabled={submitting}
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowCreate(false)}
              disabled={submitting}
            >
              {t('providers.cancel')}
            </Button>
            <Button
              type="submit"
              variant="default"
              disabled={submitting || newApiKey.length < 8}
            >
              {submitting ? '…' : t('providers.save')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
