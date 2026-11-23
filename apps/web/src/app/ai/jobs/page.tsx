'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import { getCourseCatalogCopy } from '@/features/course-catalog/copy';
import { LoadError } from '@/components/ui/LoadError';

const labels = {
  ru: { open: 'Открыть задание', empty: 'Заданий пока нет', limit: 'До 20 последних заданий', unknown: 'Статус уточняется',
    pending: 'В очереди', running: 'В работе', completed: 'Готово', failed: 'Ошибка', cancelled: 'Отменено',
    interrupted: 'Прервано', reconciliation_required: 'Ожидает сверки' },
  kk: { open: 'Тапсырманы ашу', empty: 'Әзірге тапсырмалар жоқ', limit: 'Соңғы 20 тапсырмаға дейін', unknown: 'Күйі анықталуда',
    pending: 'Кезекте', running: 'Орындалуда', completed: 'Дайын', failed: 'Қате', cancelled: 'Бас тартылды',
    interrupted: 'Үзілді', reconciliation_required: 'Тексеруді күтуде' },
  en: { open: 'Open job', empty: 'No generation jobs yet', limit: 'Up to 20 recent jobs', unknown: 'Status pending',
    pending: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled',
    interrupted: 'Interrupted', reconciliation_required: 'Reconciliation required' },
};

export default function GenerationJobsPage() {
  const { user, sessionEpoch } = useAuthStore();
  if (!user || !['methodologist', 'admin', 'superadmin'].includes(user.role)) return null;
  return <GenerationJobs key={JSON.stringify([user.tenant_id, user.user_id, sessionEpoch])} />;
}

function GenerationJobs() {
  const { lang, t } = useT();
  const copy = labels[lang] ?? labels.ru;
  const catalog = getCourseCatalogCopy(lang);
  const [jobs, setJobs] = useState<AIGenerationJob[]>();
  const [failed, setFailed] = useState(false);
  const [request, setRequest] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    void api.get<AIGenerationJob[]>('/v1/ai/jobs', { signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setJobs(data.filter(job => job.job_type === 'course_generation' || (!job.job_type && job.course_id)));
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [request]);

  const date = new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'short' });
  return <section className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold">{catalog.generationJobs}</h1>
      <Link className="rounded-xl bg-primary px-4 py-2 text-primary-foreground" href="/ai/generate?new=1">{catalog.createFromDocuments}</Link>
    </header>
    {failed ? <LoadError title={t('common.loadFailed')} retryLabel={t('common.retry')} onRetry={() => setRequest(value => value + 1)} />
      : !jobs ? <p role="status">{t('common.loading')}</p>
      : !jobs.length ? <p className="rounded-xl border border-border bg-card p-5">{copy.empty}</p>
      : <>
        <p className="text-sm text-muted-foreground">{copy.limit}</p>
        <ul className="divide-y divide-border rounded-xl border border-border bg-card">
          {jobs.map(job => <li key={job.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <p className="font-medium">{copy[job.status as keyof typeof copy] ?? copy.unknown}</p>
              <p className="text-sm text-muted-foreground"><time dateTime={job.created_at}>{date.format(new Date(job.created_at))}</time> · {job.id.slice(0, 8)}</p>
            </div>
            <Link className="rounded-lg border border-border px-3 py-2 text-primary" href={'/ai/generate?job_id=' + encodeURIComponent(job.id)}>{copy.open}</Link>
          </li>)}
        </ul>
      </>}
  </section>;
}
