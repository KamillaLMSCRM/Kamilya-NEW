'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/apiErrorMessage';
import {
  ChatGPTReadiness,
  GenerationModelRouting,
  ModelRoutingRequestError,
  getGenerationModelRouting,
  saveGenerationModelRouting,
  checkChatGPTReadiness,
  buildChatGPTReserveOrder,
} from '@/lib/adminModelRouting';
import { ChatGPTReserveControl } from '@/components/admin/ChatGPTReserveControl';
import { RuntimeSettingsControl } from '@/components/admin/RuntimeSettingsControl';

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

const CHATGPT_READINESS_REASONS = new Set(['not_configured', 'authorization_required', 'unavailable', 'protocol_mismatch', 'ready']);

function requestErrorMessage(error: unknown) {
  return apiErrorMessage(error, error instanceof Error ? error.message : 'Unknown error');
}

export default function AdminProvidersPage() {
  const { t, lang } = useT();
  const token = useAuthStore((s) => s.accessToken);

  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showRuntimeSettings, setShowRuntimeSettings] = useState(false);
  const [showRouting, setShowRouting] = useState(false);
  const [routing, setRouting] = useState<GenerationModelRouting | null>(null);
  const [routingOrder, setRoutingOrder] = useState<string[]>([]);
  const [routingLoading, setRoutingLoading] = useState(false);
  const [routingLoadError, setRoutingLoadError] = useState(false);
  const [routingSaving, setRoutingSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [showChatGPTReserve, setShowChatGPTReserve] = useState(false);
  const [chatGPTReadiness, setChatGPTReadiness] = useState<ChatGPTReadiness | null>(null);
  const [chatGPTChecking, setChatGPTChecking] = useState(false);
  const [chatGPTSaving, setChatGPTSaving] = useState(false);
  const readinessGeneration = useRef(0);
  const invalidateReadiness = useCallback(() => {
    readinessGeneration.current += 1;
    setChatGPTReadiness(null);
    setChatGPTChecking(false);
  }, []);

  useEffect(() => {
    invalidateReadiness();
    return () => { readinessGeneration.current += 1; };
  }, [token, invalidateReadiness]);

  // New-key form state
  const [newProvider, setNewProvider] = useState<'deepseek' | 'voyage' | 'cohere'>('deepseek');
  const [newApiKey, setNewApiKey] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const fetchKeys = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const response = await api.get<{ providers?: ProviderKey[] }>('/v1/admin/provider-keys');
      setKeys(response.data.providers || []);
    } catch (e) {
      toast.error(t('providers.loadError'));
    } finally {
      setLoading(false);
    }
  }, [token, t]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post('/v1/admin/provider-keys', {
          provider: newProvider,
          api_key: newApiKey,
          label: newLabel || null,
          is_active: true,
      });
      toast.success(t('providers.saveOk'));
      setShowCreate(false);
      setNewApiKey('');
      setNewLabel('');
      await fetchKeys();
    } catch (e) {
      toast.error(`${t('providers.saveError')}: ${requestErrorMessage(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleActive = async (key: ProviderKey) => {
    try {
      await api.patch(`/v1/admin/provider-keys/${key.id}`, { is_active: !key.is_active });
      await fetchKeys();
    } catch (e) {
      toast.error(t('providers.saveError'));
    }
  };

  const handleDelete = async (key: ProviderKey) => {
    const label = key.label || key.provider;
    if (!confirm(t('providers.deleteConfirm', { label }))) return;
    try {
      await api.delete(`/v1/admin/provider-keys/${key.id}`);
      toast.success(t('providers.deleteOk'));
      await fetchKeys();
    } catch (e) {
      toast.error(t('providers.deleteError'));
    }
  };

  const handleTest = async (key: ProviderKey) => {
    setTestingId(key.id);
    try {
      const response = await api.post<{ ok: boolean; latency_ms?: number; error?: string }>(`/v1/admin/provider-keys/${key.id}/test`);
      const data = response.data;
      if (data.ok) {
        toast.success(t('providers.testOk', { latency: data.latency_ms ?? 0 }));
      } else {
        toast.error(t('providers.testFail', { error: data.error || 'unknown' }));
      }
      await fetchKeys(); // refresh last_used_at + last_error
    } catch (e) {
      toast.error(t('providers.testFail', { error: requestErrorMessage(e) }));
    } finally {
      setTestingId(null);
    }
  };

  const loadRouting = useCallback(async () => {
    if (!token) return;
    setRouting(null);
    invalidateReadiness();
    setRoutingLoadError(false);
    setRoutingLoading(true);
    try {
      const data = await getGenerationModelRouting();
      setRouting(data);
      setRoutingOrder(
        data.models
          .filter((model) => model.is_enabled)
          .sort((left, right) => (left.position ?? 999) - (right.position ?? 999))
          .map((model) => model.id),
      );
    } catch (error) {
      setRoutingLoadError(true);
      toast.error(t('providers.routingLoadError'));
    } finally {
      setRoutingLoading(false);
    }
  }, [t, token, invalidateReadiness]);

  const openRouting = () => {
    setShowRouting(true);
    void loadRouting();
  };

  const chatGPTRoute = routing?.models.find((model) => model.id === 'chatgpt_reserve');
  const openChatGPTReserve = () => {
    setShowChatGPTReserve(true);
    void loadRouting();
  };
  const checkChatGPT = async () => {
    const generation = ++readinessGeneration.current;
    setChatGPTReadiness(null);
    setChatGPTChecking(true);
    try {
      const result = await checkChatGPTReadiness();
      if (generation === readinessGeneration.current) setChatGPTReadiness(result);
    } catch (error) {
      if (generation !== readinessGeneration.current) return;
      const reason = error instanceof ModelRoutingRequestError ? error.reason : undefined;
      const reasonText = reason
        ? (t as any)(`providers.chatgptReserve.reasons.${reason}`)
        : undefined;
      toast.error(reasonText || t('providers.chatgptReserve.readinessError'));
      setChatGPTReadiness(null);
    } finally {
      if (generation === readinessGeneration.current) setChatGPTChecking(false);
    }
  };
  const saveChatGPTReserve = async (enabled: boolean) => {
    if (!routing || chatGPTSaving) return;
    invalidateReadiness();
    setChatGPTSaving(true);
    try {
      const nextOrder = buildChatGPTReserveOrder(routing, enabled);
      const saved = await saveGenerationModelRouting(routing.revision, nextOrder);
      setRouting(saved);
      setRoutingOrder(saved.models.filter((model) => model.is_enabled).sort((a, b) => (a.position ?? 999) - (b.position ?? 999)).map((model) => model.id));
      setChatGPTReadiness(null);
      toast.success(t('providers.routingSaveOk'));
    } catch (error) {
      const reason = error instanceof ModelRoutingRequestError ? error.reason : undefined;
      if (error instanceof ModelRoutingRequestError && error.status === 409) {
        const reasonText = reason ? (t as any)(`providers.chatgptReserve.reasons.${reason}`) : undefined;
        toast.error(reasonText || t('providers.routingConflict'));
        await loadRouting();
      } else {
        toast.error(t('providers.chatgptReserve.saveError'));
      }
    } finally {
      setChatGPTSaving(false);
    }
  };

  const moveRoutingModel = (modelId: string, direction: -1 | 1) => {
    setRoutingOrder((current) => {
      const index = current.indexOf(modelId);
      const target = index + direction;
      if (index <= 0 || target <= 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const toggleRoutingModel = (modelId: string) => {
    setRoutingOrder((current) =>
      current.includes(modelId)
        ? current.filter((id) => id !== modelId)
        : [...current, modelId],
    );
  };

  const handleRoutingModelToggle = (modelId: string) => {
    const model = routing?.models.find((candidate) => candidate.id === modelId);
    if (modelId === 'chatgpt_reserve' && !routingOrder.includes(modelId)) {
      if (!confirm(t('providers.chatgptReserve.confirmEnable'))) return;
    }
    if (model?.activation_blocker) return;
    toggleRoutingModel(modelId);
  };

  const handleRoutingSave = async () => {
    if (!token || !routing) return;
    invalidateReadiness();
    setRoutingSaving(true);
    try {
      const saved = await saveGenerationModelRouting(routing.revision, routingOrder);
      setRouting(saved);
      setRoutingOrder(
        saved.models
          .filter((model) => model.is_enabled)
          .sort((left, right) => (left.position ?? 999) - (right.position ?? 999))
          .map((model) => model.id),
      );
      setShowRouting(false);
      toast.success(t('providers.routingSaveOk'));
    } catch (error) {
      if (error instanceof ModelRoutingRequestError && error.status === 409) {
        toast.error(error.reason
          ? (t as any)(`providers.chatgptReserve.reasons.${error.reason}`)
          : t('providers.routingConflict'));
        await loadRouting();
      } else {
        toast.error(t('providers.routingSaveError'));
      }
    } finally {
      setRoutingSaving(false);
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
          <div className="flex flex-wrap gap-2 justify-end">
            <Button variant="secondary" onClick={() => setShowRuntimeSettings((open) => !open)} aria-expanded={showRuntimeSettings}>
              {lang === 'ru' ? 'Параметры выполнения' : lang === 'kk' ? 'Орындау параметрлері' : 'Runtime settings'}
            </Button>
            <ChatGPTReserveControl
              route={chatGPTRoute}
              readiness={chatGPTReadiness}
              loading={routingLoading}
              loadError={routingLoadError}
              checking={chatGPTChecking}
              saving={chatGPTSaving}
              open={showChatGPTReserve}
              onOpen={openChatGPTReserve}
              onClose={() => setShowChatGPTReserve(false)}
              onCheck={() => void checkChatGPT()}
              onRetry={() => void loadRouting()}
              onEnable={() => void saveChatGPTReserve(true)}
              onDisable={() => void saveChatGPTReserve(false)}
            />
            <Button onClick={openRouting} variant="secondary">
              {t('providers.manageRouting')}
            </Button>
            <Button onClick={() => setShowCreate(true)} variant="default">
              + {t('providers.addKey')}
            </Button>
          </div>
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

      {showRuntimeSettings && <RuntimeSettingsControl />}

      <Modal
        open={showRouting}
        onClose={() => !routingSaving && setShowRouting(false)}
        title={t('providers.routingTitle')}
        description={t('providers.routingDescription')}
        className="max-w-2xl"
        dismissable={!routingSaving}
      >
        {routingLoading ? (
          <p className="py-8 text-center text-text-tertiary">…</p>
        ) : routing ? (
          <div className="space-y-4">
            <div className="space-y-3">
              {routing.models
                .filter((model) => routingOrder.includes(model.id))
                .sort(
                  (left, right) =>
                    routingOrder.indexOf(left.id) - routingOrder.indexOf(right.id),
                )
                .map((model, index) => (
                  <div
                    key={model.id}
                    className="rounded-lg border border-border p-3 flex gap-3 items-start"
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary font-semibold">
                      {index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{model.display_name}</span>
                        <Badge variant={model.is_configured ? 'secondary' : 'default'}>
                          {model.is_configured
                            ? t('providers.routingConfigured')
                            : t('providers.routingNotConfigured')}
                        </Badge>
                        {model.is_required && (
                          <Badge variant="secondary">{t('providers.routingRequired')}</Badge>
                        )}
                      </div>
                      <p className="mt-1 truncate text-xs text-text-tertiary">
                        {model.provider} · {model.model}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1 justify-end">
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        aria-label={t('providers.routingMoveUp', { model: model.display_name })}
                        onClick={() => moveRoutingModel(model.id, -1)}
                        disabled={index <= 1 || routingSaving}
                      >
                        ↑
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        aria-label={t('providers.routingMoveDown', { model: model.display_name })}
                        onClick={() => moveRoutingModel(model.id, 1)}
                        disabled={index === 0 || index === routingOrder.length - 1 || routingSaving}
                      >
                        ↓
                      </Button>
                      {!model.is_required && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() => handleRoutingModelToggle(model.id)}
                          disabled={routingSaving}
                        >
                          {t('providers.routingDisable')}
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
            </div>

            {routing.models.some((model) => !routingOrder.includes(model.id)) && (
              <div className="border-t border-border pt-4">
                <p className="mb-2 text-sm font-medium">{t('providers.routingAvailable')}</p>
                <div className="space-y-2">
                  {routing.models
                    .filter((model) => !routingOrder.includes(model.id))
                    .map((model) => (
                      <div
                        key={model.id}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"
                      >
                        <div className="min-w-0">
                          <p className="font-medium">{model.display_name}</p>
                          <p className="truncate text-xs text-text-tertiary">
                            {model.provider} · {model.model}
                          </p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => handleRoutingModelToggle(model.id)}
                          disabled={routingSaving || Boolean(model.activation_blocker)}
                        >
                          + {t('providers.routingAdd')}
                        </Button>
                        {model.activation_blocker && (
                          <p className="mt-1 text-xs text-text-tertiary">
                            {model.activation_blocker && CHATGPT_READINESS_REASONS.has(model.activation_blocker)
                              ? (t as any)(`providers.chatgptReserve.reasons.${model.activation_blocker}`)
                              : t('providers.chatgptReserve.reasonUnknown')}
                          </p>
                        )}
                      </div>
                    ))}
                </div>
              </div>
            )}

            <p className="text-xs text-text-tertiary">
              {t('providers.routingAppliesNextJobs')}
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setShowRouting(false)}
                disabled={routingSaving}
              >
                {t('providers.cancel')}
              </Button>
              <Button
                type="button"
                onClick={handleRoutingSave}
                disabled={routingSaving || routingOrder[0] !== 'deepseek'}
              >
                {routingSaving ? '…' : t('providers.save')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 py-4 text-center">
            <p className="text-text-secondary">{t('providers.routingLoadError')}</p>
            <Button type="button" variant="secondary" onClick={() => void loadRouting()}>
              {t('providers.routingRetry')}
            </Button>
          </div>
        )}
      </Modal>

      {/* Add-key modal */}
      <Modal
        open={showCreate}
        onClose={() => !submitting && setShowCreate(false)}
        title={t('providers.addKeyTitle')}
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label htmlFor="provider-key-provider" className="block text-sm font-medium mb-1">
              {t('providers.provider')}
            </label>
            <select
              id="provider-key-provider"
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
            <label htmlFor="provider-key-api-key" className="block text-sm font-medium mb-1">
              {t('providers.apiKey')}
            </label>
            <Input
              id="provider-key-api-key"
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
            <label htmlFor="provider-key-label" className="block text-sm font-medium mb-1">
              {t('providers.label')}
            </label>
            <Input
              id="provider-key-label"
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
