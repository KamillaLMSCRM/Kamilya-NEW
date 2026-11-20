'use client';

import { useEffect, useState } from 'react';

import { useT, type TranslationKey } from '@/i18n/useT';
import { api } from '@/lib/api';
import { TELEGRAM_LEARNING_API } from './TelegramSubscription';

export interface TelegramDelivery {
  id: string;
  step: string;
  status: string;
  reason: string | null;
  scheduled_at: string;
  sent_at: string | null;
}

const STATUS_KEYS: Record<string, TranslationKey> = {
  queued: 'learningTelegram.status.queued',
  dispatching: 'learningTelegram.status.sending',
  sent: 'learningTelegram.status.sent',
  failed: 'learningTelegram.status.failed',
  uncertain: 'learningTelegram.status.uncertain',
  skipped: 'learningTelegram.status.skipped',
};

const STEP_KEYS: Record<string, TranslationKey> = {
  assigned: 'learningTelegram.steps.assigned',
  before_due: 'learningTelegram.steps.beforeDue',
  overdue: 'learningTelegram.steps.overdue',
};

export function TelegramDeliveryLine({ delivery }: { delivery: TelegramDelivery }) {
  const { t } = useT();
  const statusKey = delivery.reason === 'not_connected' ? 'learningTelegram.disconnected' : STATUS_KEYS[delivery.status];
  return (
    <span>
      Telegram · {t(STEP_KEYS[delivery.step] ?? 'learningTelegram.title')} · {t(statusKey ?? 'learningTelegram.status.unknown')}
      {delivery.sent_at ? ` · ${new Date(delivery.sent_at).toLocaleString()}` : ''}
    </span>
  );
}

export function TelegramAssignmentStatus({ enrollmentId }: { enrollmentId: string }) {
  const [deliveries, setDeliveries] = useState<TelegramDelivery[]>([]);
  useEffect(() => {
    const request = new AbortController();
    void api.get<TelegramDelivery[]>(`${TELEGRAM_LEARNING_API}/delivery/course/${enrollmentId}`, { signal: request.signal })
      .then(({ data }) => { if (!request.signal.aborted) setDeliveries(data); })
      .catch(() => { /* Email statuses use their existing independent read. */ });
    return () => request.abort();
  }, [enrollmentId]);
  if (deliveries.length === 0) return null;
  return <ul className="space-y-1 text-xs text-muted-foreground">{deliveries.map((delivery) => (
    <li key={delivery.id}><TelegramDeliveryLine delivery={delivery} /></li>
  ))}</ul>;
}

export function TelegramLearnerStatus({ learnerId }: { learnerId: string }) {
  const { t } = useT();
  const [connected, setConnected] = useState<boolean>();
  useEffect(() => {
    const request = new AbortController();
    void api.get<{ available: boolean; connected: boolean }>(`${TELEGRAM_LEARNING_API}/learner/${learnerId}`, { signal: request.signal })
      .then(({ data }) => { if (!request.signal.aborted && data.available) setConnected(data.connected); })
      .catch(() => { /* The rest of the learner panel is independent. */ });
    return () => request.abort();
  }, [learnerId]);
  return connected === undefined ? null : <p className="text-xs text-muted-foreground">{t(connected ? 'learningTelegram.connected' : 'learningTelegram.disconnected')}</p>;
}
