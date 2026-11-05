'use client';

import { useCallback, useEffect, useState } from 'react';
import { Copy, RefreshCw, Send } from 'lucide-react';
import { Badge, Button, Input } from '@/components/ui';
import { WorkspacePage, WorkspacePanel, WorkspaceEmpty } from '@/features/workspace-design';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT, type TranslationKey } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { LoadError } from '@/components/ui/LoadError';

interface DeliveryFields {
  delivery_status: 'pending' | 'sent' | 'failed';
  delivery_message_id: string | null;
  delivery_last_attempt_at: string | null;
  delivery_attempt_count: number;
  delivery_failure_category: string | null;
  delivery_failure_message: string | null;
}
interface Invitation extends DeliveryFields { id: string; email: string; role: string; status: string; created_at: string; expires_at: string; accepted_at: string | null; }
interface InviteLink extends DeliveryFields { email: string; invite_url: string; }
const statusVariant = (status: string) => status === 'accepted' ? 'default' : status === 'pending' ? 'outline' : 'secondary';
const deliveryVariant = (status: string) => status === 'sent' ? 'default' : status === 'failed' ? 'destructive' : 'outline';
const describeError = (
  error: any,
  fallback: string,
  translate: (key: TranslationKey) => string,
) => {
  const response = error?.response;
  const detail = response?.data?.detail;
  if (detail?.code === 'demo_limit_exceeded') return translate('invitations.demoUnavailable');
  if (response?.status === 403) return translate('invitations.permissionError');
  if (response?.status >= 500) return translate('invitations.serverError');
  return typeof detail === 'string' ? detail : fallback;
};

export default function InvitationsPage() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const isDemoTenant = Boolean(user?.tenant?.is_demo);
  const [email, setEmail] = useState('');
  const [items, setItems] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviteUrls, setInviteUrls] = useState<InviteLink[]>([]);

  const load = useCallback(async () => {
    if (!token) return;
    if (isDemoTenant) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const response = await api.get('/v1/users/invitations?per_page=100');
      setItems(response.data.items || []);
    } catch (error: any) {
      const message = describeError(error, t('invitations.loadError'), t);
      setLoadError(message);
      toast.error(t('invitations.loadError'), { description: message });
    } finally { setLoading(false); }
  }, [isDemoTenant, token, t]);
  useEffect(() => { load(); }, [load]);

  const createInvitation = async () => {
    const value = email.trim().toLowerCase();
    if (!value || !value.includes('@')) { toast.error(t('invitations.emailRequired')); return; }
    setSubmitting(true);
    try {
      const response = await api.post('/v1/users/invitations/bulk', { items: [{ email: value }] });
      setInviteUrls((response.data.created || []).map((item: InviteLink) => item));
      setEmail(''); await load(); toast.success(t('invitations.created'));
    } catch (error: any) { toast.error(t('invitations.createError'), { description: describeError(error, t('invitations.createError'), t) }); }
    finally { setSubmitting(false); }
  };
  const resend = async (id: string) => {
    try { const response = await api.post(`/v1/users/invitations/${id}/resend`); setInviteUrls([{ ...response.data, email: response.data.email || t('invitations.resentEmail') }]); await load(); toast.success(t('invitations.resent')); }
    catch (error: any) { toast.error(t('invitations.resendError'), { description: describeError(error, t('invitations.resendError'), t) }); }
  };
  const copy = async (url: string) => { await navigator.clipboard.writeText(url); toast.success(t('invitations.copied')); };

  return (
    <WorkspacePage id="invitations" title={t('invitations.title')} description={t('invitations.subtitle')} icon={<Send />} className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)]">
      <div className="min-w-0 space-y-5">
      {isDemoTenant ? <WorkspacePanel title={t('invitations.demoUnavailable')} className="border-warning/30 bg-warning/5"><p className="text-sm text-muted-foreground">{t('invitations.demoHint')}</p></WorkspacePanel> : <WorkspacePanel title={t('invitations.createTitle')} bodyClassName="space-y-4">
        <label className="block space-y-2 text-sm font-medium"><span>{t('invitations.emailLabel')}</span>
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') createInvitation(); }} placeholder={t('invitations.emailPlaceholder')} aria-label={t('invitations.emailLabel')} />
        </label>
        <Button className="w-full gap-2 sm:w-auto" onClick={createInvitation} disabled={submitting || !email.trim()}><Send className="h-4 w-4" aria-hidden="true" />{submitting ? t('invitations.creating') : t('invitations.createButton')}</Button>
      </WorkspacePanel>}
      {inviteUrls.length > 0 && <WorkspacePanel title={t('invitations.linksTitle')} className="border-primary/25" bodyClassName="space-y-4">
        {inviteUrls.map((item) => <div key={`${item.email}-${item.invite_url}`} className="space-y-3 border-b border-border pb-4 last:border-0 last:pb-0"><p className="break-all text-sm font-medium">{item.email}</p><div className="flex min-w-0 gap-2"><Input readOnly value={item.invite_url} className="min-w-0 font-mono text-xs" /><Button variant="outline" size="sm" className="shrink-0" onClick={() => copy(item.invite_url)} title={t('invitations.copy')}><Copy className="h-4 w-4" aria-hidden="true" /><span className="sr-only">{t('invitations.copy')}</span></Button></div><div className="flex flex-wrap items-center gap-2 text-xs"><Badge variant={deliveryVariant(item.delivery_status) as any}>{t(`invitations.delivery.${item.delivery_status}` as TranslationKey)}</Badge>{item.delivery_status === 'sent' ? <span className="text-muted-foreground">{t('invitations.deliveryAccepted')}</span> : item.delivery_status === 'failed' ? <span className="text-destructive">{item.delivery_failure_message || t('invitations.deliveryFailureHint')}</span> : <span className="text-muted-foreground">{t('invitations.deliveryPendingHint')}</span>}</div></div>)}
        <p className="text-xs text-muted-foreground">{t('invitations.manualDeliveryHint')}</p>
      </WorkspacePanel>}
      </div>
      <WorkspacePanel title={t('invitations.listTitle')} actions={<Button variant="outline" size="sm" className="gap-2" onClick={load} disabled={loading} title={t('invitations.refresh')}><RefreshCw className="h-4 w-4" aria-hidden="true" />{t('invitations.refresh')}</Button>} padded={false}>
        {loading ? <p role="status" className="p-6 text-sm text-muted-foreground">{t('common.loading')}</p> : loadError ? <div className="p-5"><LoadError title={t('invitations.loadError')} message={loadError} retryLabel={t('common.retry')} onRetry={load} /></div> : items.length === 0 ? <div className="p-5"><WorkspaceEmpty title={t('invitations.empty')} icon={<Send />} /></div> : <div className="divide-y divide-border">{items.map((item) => <article key={item.id} className="grid min-w-0 gap-4 px-5 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"><div className="min-w-0"><h3 className="break-all font-medium text-foreground">{item.email}</h3><p className="mt-1 text-xs text-muted-foreground">{t('invitations.expiresAt')}: {new Date(item.expires_at).toLocaleDateString()}</p>{item.delivery_status === 'failed' && <p className="mt-2 break-words text-xs text-destructive">{item.delivery_failure_message || t('invitations.deliveryFailureHint')}</p>}</div><div className="flex flex-wrap items-center gap-2 sm:max-w-60 sm:justify-end"><Badge variant={statusVariant(item.status) as any}>{t(`invitations.status.${item.status}` as any) || item.status}</Badge><Badge variant={deliveryVariant(item.delivery_status) as any}>{t(`invitations.delivery.${item.delivery_status}` as TranslationKey)}</Badge>{(item.status === 'pending' || item.delivery_status === 'failed') && <Button variant="outline" size="sm" className="gap-2" onClick={() => resend(item.id)}><RefreshCw className="h-4 w-4" aria-hidden="true" />{t('invitations.resend')}</Button>}</div></article>)}</div>}
      </WorkspacePanel>
      </div>
    </WorkspacePage>
  );
}
