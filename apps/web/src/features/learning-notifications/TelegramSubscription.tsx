'use client';

import { useEffect, useRef, useState } from 'react';

import { Button, Input } from '@/components/ui';
import { WorkspacePanel } from '@/features/workspace-design';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';

export const TELEGRAM_LEARNING_API = '/v1/learning-notifications/telegram';

interface Subscription {
  available: boolean;
  connected: boolean;
  pending_confirmation: boolean;
}

export function TelegramSubscription() {
  const { t } = useT();
  const [subscription, setSubscription] = useState<Subscription>();
  const [link, setLink] = useState('');
  const [code, setCode] = useState('');
  const [action, setAction] = useState(false);
  const [error, setError] = useState(false);
  const mounted = useRef(false);

  useEffect(() => {
    const request = new AbortController();
    mounted.current = true;
    void api.get<Subscription>(`${TELEGRAM_LEARNING_API}/subscription`, { signal: request.signal })
      .then(({ data }) => { if (!request.signal.aborted) setSubscription(data); })
      .catch(() => { /* Other profile sections remain available. */ });
    return () => { mounted.current = false; request.abort(); };
  }, []);

  async function update(kind: 'link' | 'confirm' | 'disconnect') {
    setAction(true);
    setError(false);
    try {
      if (kind === 'link') {
        const { data } = await api.post<{ url: string }>(`${TELEGRAM_LEARNING_API}/subscription/link`);
        if (mounted.current) {
          setLink(data.url);
          setCode('');
        }
      } else {
        const path = `${TELEGRAM_LEARNING_API}/subscription`;
        const { data } = kind === 'confirm'
          ? await api.post<Subscription>(`${path}/confirm`, { code: code.trim() })
          : await api.delete<Subscription>(path);
        if (mounted.current) {
          setSubscription(data);
          setLink('');
          setCode('');
        }
      }
    } catch {
      if (mounted.current) setError(true);
    } finally {
      if (mounted.current) setAction(false);
    }
  }

  if (!subscription?.available) return null;
  const pending = Boolean(link || subscription.pending_confirmation) && !subscription.connected;
  return (
    <WorkspacePanel title={t('learningTelegram.title')} bodyClassName="space-y-3">
      <p className="text-sm" role="status">{t(subscription.connected ? 'learningTelegram.connected' : 'learningTelegram.disconnected')}</p>
      <p className="text-sm text-muted-foreground">{t('learningTelegram.emailContinues')}</p>
      {subscription.connected ? (
        <Button variant="outline" disabled={action} onClick={() => void update('disconnect')}>{t('learningTelegram.disconnect')}</Button>
      ) : (
        <>
          {link ? (
            <a className="inline-block font-medium text-primary underline underline-offset-4" href={link} target="_blank" rel="noreferrer">
              {t('learningTelegram.openBot')}
            </a>
          ) : (
            <Button variant="outline" disabled={action} onClick={() => void update('link')}>{t('learningTelegram.connect')}</Button>
          )}
          {pending && (
            <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void update('confirm'); }}>
              <label htmlFor="telegram-notification-link-code" className="block text-sm font-medium">{t('learningTelegram.codeLabel')}</label>
              <Input id="telegram-notification-link-code" autoComplete="one-time-code" maxLength={12} value={code}
                onChange={(event) => setCode(event.target.value)} />
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={action || !/^[a-f0-9]{12}$/i.test(code.trim())}>{t('learningTelegram.confirm')}</Button>
                {link && <Button type="button" variant="ghost" disabled={action} onClick={() => void update('link')}>{t('learningTelegram.renew')}</Button>}
              </div>
            </form>
          )}
        </>
      )}
      {error && <p className="text-sm text-destructive" role="alert">{t('learningTelegram.updateFailed')}</p>}
    </WorkspacePanel>
  );
}
