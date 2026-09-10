'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import {
  getTenantAiSettings, saveTenantAiSetting, removeTenantAiSetting,
  type AiPurpose, type TenantAiProvider, type TenantAiSetting,
} from '@/lib/tenantAiProviders';

export default function TenantAiSettingsPage() {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.accessToken);
  if (!token || !user?.tenant_id || user.role !== 'admin') {
    return <p role="alert">{t('tenantAi.accessDenied')}</p>;
  }
  return <Settings key={`${user.user_id}:${user.tenant_id}:${user.role}`} token={token} />;
}

function Settings({ token }: { token: string }) {
  const { t } = useT();
  const [settings, setSettings] = useState<TenantAiSetting[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState('loading');
    getTenantAiSettings(token, controller.signal).then((rows) => {
      if (!controller.signal.aborted) { setSettings(rows); setState('ready'); }
    }).catch(() => { if (!controller.signal.aborted) setState('error'); });
    return () => controller.abort();
  }, [token, reload]);
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header><h1 className="text-2xl font-bold">{t('tenantAi.title')}</h1><p className="mt-2 text-muted-foreground">{t('tenantAi.subtitle')}</p></header>
      <p className="rounded-xl border border-border bg-muted/40 p-4 text-sm">{t('tenantAi.privacy')}</p>
      {state === 'loading' && <p role="status">{t('common.loading')}</p>}
      {state === 'error' && <div role="alert"><p>{t('tenantAi.loadError')}</p><Button className="mt-3" onClick={() => setReload((n) => n + 1)}>{t('tenantAi.retry')}</Button></div>}
      {state === 'ready' && <div className="grid gap-6 md:grid-cols-2">{(['generation', 'embedding'] as const).map((purpose) => (
        <ProviderForm key={purpose} purpose={purpose} token={token} initial={settings.find((s) => s.purpose === purpose)} />
      ))}</div>}
    </div>
  );
}

function ProviderForm({ purpose, token, initial }: { purpose: AiPurpose; token: string; initial?: TenantAiSetting }) {
  const { t } = useT();
  const [saved, setSaved] = useState(initial);
  const [provider, setProvider] = useState<TenantAiProvider>(initial?.provider ?? (purpose === 'generation' ? 'openrouter' : 'voyage'));
  const [model, setModel] = useState(initial?.model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [freeOnly, setFreeOnly] = useState(initial?.free_only ?? true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<'saved' | 'removed' | 'error' | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    controller.current = new AbortController();
    setApiKey('');
    return () => controller.current?.abort();
  }, [token]);
  const providers: TenantAiProvider[] = purpose === 'generation' ? ['openrouter', 'deepseek'] : ['voyage', 'cohere', 'openrouter'];
  const hasSavedKey = saved?.has_key && provider === saved.provider;
  const validFreeModel = provider !== 'openrouter' || !freeOnly || model.endsWith(':free') || (purpose === 'generation' && model === 'openrouter/free');
  const canSave = Boolean(model.trim()) && Boolean(apiKey.trim() || hasSavedKey) && validFreeModel;
  async function submit(remove = false) {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted) return;
    setBusy(true); setMessage(null);
    try {
      if (remove) {
        await removeTenantAiSetting(token, purpose, signal);
        if (signal.aborted) return;
        setSaved(undefined); setModel(''); setMessage('removed');
      } else {
        const body = { provider, model: model.trim(), enabled, free_only: provider === 'openrouter' && freeOnly, output_dimensions: null, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) };
        await saveTenantAiSetting(token, purpose, body, signal);
        if (signal.aborted) return;
        const rows = await getTenantAiSettings(token, signal);
        if (signal.aborted) return;
        setSaved(rows.find((s) => s.purpose === purpose)); setMessage('saved');
      }
    } catch { if (!signal.aborted) setMessage('error'); }
    finally { if (!signal.aborted) { setApiKey(''); setBusy(false); } }
  }
  return (
    <Card><CardContent className="space-y-4 p-5">
      <h2 className="text-lg font-semibold">{t(purpose === 'generation' ? 'tenantAi.generation' : 'tenantAi.embedding')}</h2>
      <p className="text-sm text-muted-foreground">{t(purpose === 'generation' ? 'tenantAi.generationHelp' : 'tenantAi.embeddingHelp')}</p>
      <p className="text-sm">{t(saved?.enabled ? 'tenantAi.ownModel' : 'tenantAi.platformModel')}</p>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (canSave && !busy) void submit(); }}>
        <label className="block space-y-1 text-sm"><span>{t('tenantAi.provider')}</span>
          <select className="h-10 w-full rounded-md border border-input bg-background px-3" value={provider} disabled={busy} onChange={(event) => { setProvider(event.target.value as TenantAiProvider); setApiKey(''); setModel(''); setFreeOnly(true); setMessage(null); }}>
            {providers.map((item) => <option key={item} value={item}>{item === 'openrouter' ? 'OpenRouter' : item === 'deepseek' ? 'DeepSeek' : item === 'voyage' ? 'Voyage AI' : 'Cohere'}</option>)}
          </select>
        </label>
        <label className="block space-y-1 text-sm"><span>{t('tenantAi.model')}</span><Input value={model} maxLength={128} disabled={busy} onChange={(e) => { setModel(e.target.value); setMessage(null); }} placeholder={provider === 'openrouter' && purpose === 'generation' ? 'openrouter/free' : undefined} autoComplete="off" /></label>
        <label className="block space-y-1 text-sm"><span>{t('tenantAi.key')}</span><Input type="password" value={apiKey} maxLength={512} disabled={busy} onChange={(e) => setApiKey(e.target.value)} autoComplete="new-password" spellCheck={false} /></label>
        <p className="text-xs text-muted-foreground">{t(hasSavedKey ? 'tenantAi.keySaved' : 'tenantAi.keyRequired')}</p>
        {provider === 'openrouter' && <div className="space-y-2"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={freeOnly} disabled={busy} onChange={(e) => setFreeOnly(e.target.checked)} />{t('tenantAi.freeOnly')}</label><p className="text-xs text-muted-foreground">{t('tenantAi.freeHelp')}</p>{!validFreeModel && <p role="alert" className="text-sm text-destructive">{t('tenantAi.freeModelRequired')}</p>}</div>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} disabled={busy} onChange={(e) => setEnabled(e.target.checked)} />{t('tenantAi.enabled')}</label>
        <div className="flex flex-wrap gap-2"><Button type="submit" disabled={!canSave || busy}>{t(busy ? 'common.saving' : 'common.save')}</Button>{saved && <Button type="button" variant="outline" disabled={busy} onClick={() => { if (window.confirm(t('tenantAi.removeConfirm'))) void submit(true); }}>{t('tenantAi.remove')}</Button>}</div>
      </form>
      {message && <p role={message === 'error' ? 'alert' : 'status'} className="text-sm">{t(message === 'saved' ? 'tenantAi.saved' : message === 'removed' ? 'tenantAi.removed' : 'tenantAi.saveError')}</p>}
    </CardContent></Card>
  );
}
