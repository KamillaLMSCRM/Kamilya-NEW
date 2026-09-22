'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

const copy = {
  ru: { title: 'Ход обучения сотрудников', assigned: 'Ещё не начали', active: 'В процессе', overdue: 'Просрочено', link: 'Открыть журнал обучения', hint: 'Текущие назначения — без отменённых и заменённых записей. Историю можно включить в журнале.', unavailable: 'Сводка недоступна. Откройте журнал или обновите страницу.', current: 'Текущие назначения', completed: 'Завершено', failed: 'Не сдали', exhausted: 'Попытки исчерпаны', reassigned: 'Назначено повторно', cancelled: 'Отменено в истории', superseded: 'Заменено в истории' },
  kk: { title: 'Қызметкерлердің оқу барысы', assigned: 'Әлі бастамаған', active: 'Оқып жатыр', overdue: 'Мерзімі өткен', link: 'Оқу журналын ашу', hint: 'Ағымдағы тағайындауларға тоқтатылған және ауыстырылған жазбалар кірмейді. Тарихты журналдан қосуға болады.', unavailable: 'Жиынтық қолжетімсіз. Журналды ашыңыз немесе бетті жаңартыңыз.', current: 'Ағымдағы тағайындаулар', completed: 'Аяқталды', failed: 'Өтпеді', exhausted: 'Әрекет саны таусылды', reassigned: 'Қайта тағайындалды', cancelled: 'Тарихта тоқтатылды', superseded: 'Тарихта ауыстырылды' },
  en: { title: 'Employee learning progress', assigned: 'Not started', active: 'In progress', overdue: 'Overdue', link: 'Open training log', hint: 'Current assignments exclude cancelled and superseded records. History can be included in the log.', unavailable: 'Summary unavailable. Open the log or reload the page.', current: 'Current assignments', completed: 'Completed', failed: 'Failed', exhausted: 'Attempts exhausted', reassigned: 'Reassigned', cancelled: 'Cancelled history', superseded: 'Superseded history' },
};

function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

export function TrainingOverview() {
  const { user, accessToken } = useAuthStore();
  const { lang } = useT();
  const c = copy[lang === 'kk' || lang === 'en' ? lang : 'ru'];
  const identity = `${user?.tenant_id ?? ''}:${user?.user_id ?? ''}:${user?.role ?? ''}`;
  const [state, setState] = useState<{ identity: string; token: string; data: Record<string, unknown> | null; error: boolean } | null>(null);

  useEffect(() => {
    if (user?.role !== 'methodologist' || !accessToken) return;
    const controller = new AbortController();
    api.get('/v1/admin/training-log/summary', { signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted) setState({ identity, token: accessToken, data, error: !data || typeof data !== 'object' || Array.isArray(data) });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ identity, token: accessToken, data: null, error: true });
      });
    return () => controller.abort();
  }, [identity, user?.role, accessToken]);

  if (user?.role !== 'methodologist' || !accessToken) return null;
  const current = state?.identity === identity && state?.token === accessToken ? state : null;
  const data = current?.error ? null : current?.data;
  return (
    <section aria-labelledby="training-overview-title" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="training-overview-title" className="text-lg font-bold">{c.title}</h2>
        <Link href="/training-log" className="text-sm font-semibold text-primary underline underline-offset-4">{c.link}</Link>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {[[c.current, data?.total], [c.assigned, data?.assigned], [c.active, data?.in_progress], [c.completed, data?.completed], [c.overdue, data?.overdue], [c.failed, data?.failed_current], [c.exhausted, data?.exhausted_attempts], [c.reassigned, data?.reassigned], [c.cancelled, data?.cancelled_history], [c.superseded, data?.superseded_history]].map(([label, value]) => <div key={String(label)}><dt className="text-sm text-muted-foreground">{String(label)}</dt><dd className="mt-1 text-2xl font-semibold">{count(value) ?? '—'}</dd></div>)}
      </dl>
      <p className="mt-4 text-sm text-muted-foreground" role={current?.error ? 'status' : undefined}>{current?.error ? c.unavailable : c.hint}</p>
    </section>
  );
}
