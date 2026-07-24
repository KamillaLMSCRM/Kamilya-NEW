'use client';

import { useCallback, useEffect, useState } from 'react';
import { Copy, RefreshCw, Send } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT, type TranslationKey } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { LoadError } from '@/components/ui/LoadError';

interface Invitation { id: string; email: string; role: string; status: string; created_at: string; expires_at: string; accepted_at: string | null; }
const statusVariant = (status: string) => status === 'accepted' ? 'default' : status === 'pending' ? 'outline' : 'secondary';
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
  const [inviteUrls, setInviteUrls] = useState<Array<{ email: string; invite_url: string }>>([]);

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
      setInviteUrls((response.data.created || []).map((item: any) => ({ email: item.email, invite_url: item.invite_url })));
      setEmail(''); await load(); toast.success(t('invitations.created'));
    } catch (error: any) { toast.error(t('invitations.createError'), { description: describeError(error, t('invitations.createError'), t) }); }
    finally { setSubmitting(false); }
  };
  const resend = async (id: string) => {
    try { const response = await api.post(`/v1/users/invitations/${id}/resend`); setInviteUrls([{ email: t('invitations.resentEmail'), invite_url: response.data.invite_url }]); await load(); toast.success(t('invitations.resent')); }
    catch (error: any) { toast.error(t('invitations.resendError'), { description: describeError(error, t('invitations.resendError'), t) }); }
  };
  const copy = async (url: string) => { await navigator.clipboard.writeText(url); toast.success(t('invitations.copied')); };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header><h1 className="text-2xl font-semibold text-foreground">{t('invitations.title')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('invitations.subtitle')}</p></header>
      {isDemoTenant ? <Card className="border-warning/30 bg-warning/5"><CardHeader><CardTitle>{t('invitations.demoUnavailable')}</CardTitle></CardHeader><CardContent><p className="text-sm text-muted-foreground">{t('invitations.demoHint')}</p></CardContent></Card> : <Card><CardHeader><CardTitle>{t('invitations.createTitle')}</CardTitle></CardHeader><CardContent className="flex flex-col gap-3 sm:flex-row">
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') createInvitation(); }} placeholder={t('invitations.emailPlaceholder')} aria-label={t('invitations.emailLabel')} />
        <Button onClick={createInvitation} disabled={submitting || !email.trim()}><Send className="h-4 w-4" aria-hidden="true" />{submitting ? t('invitations.creating') : t('invitations.createButton')}</Button>
      </CardContent></Card>}
      {inviteUrls.length > 0 && <Card className="border-success/30 bg-success/5"><CardHeader><CardTitle>{t('invitations.linksTitle')}</CardTitle></CardHeader><CardContent className="space-y-3">
        {inviteUrls.map((item) => <div key={`${item.email}-${item.invite_url}`} className="flex flex-col gap-2 sm:flex-row sm:items-center"><span className="text-sm font-medium">{item.email}</span><Input readOnly value={item.invite_url} className="font-mono text-xs" /><Button variant="outline" size="sm" onClick={() => copy(item.invite_url)} title={t('invitations.copy')}><Copy className="h-4 w-4" aria-hidden="true" /><span className="sr-only">{t('invitations.copy')}</span></Button></div>)}
        <p className="text-xs text-muted-foreground">{t('invitations.manualDeliveryHint')}</p>
      </CardContent></Card>}
      <Card><CardHeader className="flex flex-row items-center justify-between gap-3"><CardTitle>{t('invitations.listTitle')}</CardTitle><Button variant="outline" size="sm" onClick={load} disabled={loading} title={t('invitations.refresh')}><RefreshCw className="h-4 w-4" aria-hidden="true" /><span className="sr-only">{t('invitations.refresh')}</span></Button></CardHeader><CardContent>
        {loading ? <p className="text-sm text-muted-foreground">{t('common.loading')}</p> : loadError ? <LoadError title={t('invitations.loadError')} message={loadError} retryLabel={t('common.retry')} onRetry={load} /> : items.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">{t('invitations.empty')}</p> : <div className="divide-y divide-border">{items.map((item) => <div key={item.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><p className="truncate font-medium text-foreground">{item.email}</p><p className="text-xs text-muted-foreground">{t('invitations.expiresAt')}: {new Date(item.expires_at).toLocaleDateString()}</p></div><Badge variant={statusVariant(item.status) as any}>{t(`invitations.status.${item.status}` as any) || item.status}</Badge>{item.status === 'pending' && <Button variant="outline" size="sm" onClick={() => resend(item.id)}><RefreshCw className="h-4 w-4" aria-hidden="true" />{t('invitations.resend')}</Button>}</div>)}</div>}
      </CardContent></Card>
    </div>
  );
}
