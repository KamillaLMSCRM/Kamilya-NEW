'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Badge, Button } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { buildTrainingLogBrowserHref, buildTrainingLogPageQuery } from '@/app/admin/training-log/query';
import { LearnerAnswers, canUseLearningInsights } from '@/features/learning-insights/LearningInsights';
import { useLearningInsightsT } from '@/features/learning-insights/i18n';
import { EmployeeKnowledgeChecks, useEmployeeKnowledgeCopy } from './EmployeeKnowledgeChecks';
import Link from 'next/link';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

type EnrollmentStatus = 'assigned' | 'in_progress' | 'completed' | 'cancelled' | 'superseded';
type CertificateStatus = 'none' | 'active' | 'expiring' | 'expired' | 'revoked';

interface EmployeeEnrollment {
  user_id: string;
  full_name: string;
  personnel_number: string | null;
  department_name: string | null;
  organization_unit_path?: string[];
  position_name: string | null;
  enrollment_id: string;
  enrollment_status: string;
  course_title: string;
  content_release_version?: number | null;
  progress_percent: number;
  computed_status: EnrollmentStatus;
  enrolled_at: string | null;
  completed_at: string | null;
  assignment_due_at?: string | null;
  cycle_due_at?: string | null;
  deadline_state?: string;
  deadline_status?: string;
  delivery_type: 'native' | 'scorm';
  quiz_attempts_count: number;
  best_score: number | null;
  certificate_id: string | null;
  certificate_number: string | null;
  certificate_issued_at: string | null;
  certificate_expires_at?: string | null;
  certificate_status?: CertificateStatus;
  latest_evidence_event_id: string | null;
  evidence_confirmation_status?: 'not_required' | 'pending' | 'confirmed';
  evidence_events?: Array<{
    event_id: string;
    procedure_type: string;
    confirmation_status: 'not_required' | 'pending' | 'confirmed';
    signed_copy_status: 'awaiting_return' | 'uploaded_pending_review' | 'accepted' | 'replacement_requested';
  }>;
}

interface JournalPage { items: EmployeeEnrollment[]; total: number }

const PAGE_SIZE = 12;
const labels = {
  ru: { card: 'Карточка сотрудника', back: 'Назад в журнал', assignments: 'Все назначения сотрудника', current: 'Текущие назначения', history: 'Включить историю', empty: 'Назначений пока нет.', unavailable: 'Назначение недоступно.', attempts: 'Попытки тестов', issued: 'Выдан', noCertificate: 'Сертификат не выдан', lastAssignment: 'Назначено', download: 'Скачать PDF сертификата', verify: 'Проверить сертификат', hideAnswers: 'Свернуть ответы' },
  kk: { card: 'Қызметкер карточкасы', back: 'Журналға қайту', assignments: 'Қызметкердің барлық тағайындаулары', current: 'Ағымдағы тағайындаулар', history: 'Тарихты қосу', empty: 'Тағайындаулар әлі жоқ.', unavailable: 'Тағайындау қолжетімсіз.', attempts: 'Тест әрекеттері', issued: 'Берілген күні', noCertificate: 'Сертификат берілмеген', lastAssignment: 'Тағайындалған күні', download: 'Сертификаттың PDF файлын жүктеу', verify: 'Сертификатты тексеру', hideAnswers: 'Жауаптарды жинау' },
  en: { card: 'Employee record', back: 'Back to training log', assignments: 'All employee assignments', current: 'Current assignments', history: 'Include history', empty: 'No assignments yet.', unavailable: 'This assignment is unavailable.', attempts: 'Test attempts', issued: 'Issued', noCertificate: 'No certificate issued', lastAssignment: 'Assigned on', download: 'Download certificate PDF', verify: 'Verify certificate', hideAnswers: 'Hide answers' },
} as const;

export function useEmployeeLearningCopy() {
  const { lang } = useT();
  return labels[lang];
}

export function EmployeeLearning({ employeeId, enrollmentId, showIdentity = false }: {
  employeeId: string;
  enrollmentId?: string;
  showIdentity?: boolean;
}) {
  const { t, lang } = useT();
  const copy = useEmployeeLearningCopy();
  const knowledgeCopy = useEmployeeKnowledgeCopy();
  const token = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  const canInspect = canUseLearningInsights(user);
  const [selection, setSelection] = useState(enrollmentId);
  const [section, setSection] = useState<'courses' | 'checks'>('courses');
  const [identity, setIdentity] = useState<{ token: string; row: EmployeeEnrollment }>();
  const [history, setHistory] = useState(false);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ query: string; token: string; value: JournalPage | null }>();
  const query = buildTrainingLogPageQuery(
    { user_id: employeeId, enrollment_id: selection, history: selection ? true : history || undefined },
    '', selection ? 1 : PAGE_SIZE, selection ? 0 : offset,
  );

  useEffect(() => {
    if (!token || !canInspect) return;
    const controller = new AbortController();
    void api.get<JournalPage>('/v1/admin/training-log?' + query, { signal: controller.signal })
      .then(({ data }) => {
        if (controller.signal.aborted) return;
        const items = data.items.filter((row) => row.user_id === employeeId && (!selection || row.enrollment_id === selection));
        setResult({ query, token, value: { ...data, items } });
        if (items[0]) setIdentity({ token, row: items[0] });
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ query, token, value: null });
      });
    return () => controller.abort();
  }, [canInspect, employeeId, query, retry, selection, token]);

  if (!canInspect) return null;
  const current = result?.query === query && result.token === token ? result.value : undefined;
  const visibleIdentity = current?.items[0] ?? (identity?.token === token && identity.row.user_id === employeeId ? identity.row : null);
  const date = (value: string | null | undefined) => {
    const parsed = value ? new Date(value) : null;
    return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleDateString(lang) : '—';
  };

  return <div className="min-w-0 space-y-4">
    {showIdentity && visibleIdentity && (
      <header className="space-y-1">
        <h3 className="text-xl font-semibold [overflow-wrap:anywhere]">{visibleIdentity.full_name}</h3>
        <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
          {[
            visibleIdentity.personnel_number && t('trainingLog.table.personnelNumber') + ' ' + visibleIdentity.personnel_number,
            visibleIdentity.position_name,
            visibleIdentity.organization_unit_path?.join(' / ') || visibleIdentity.department_name,
          ].filter(Boolean).join(' · ')}
        </p>
      </header>
    )}
    <div className="flex flex-wrap gap-2 border-b border-border pb-2">
      <Button type="button" variant={section === 'courses' ? 'default' : 'ghost'} aria-pressed={section === 'courses'}
        onClick={() => setSection('courses')}>{t('trainingLog.table.course')}</Button>
      <Button type="button" variant={section === 'checks' ? 'default' : 'ghost'} aria-pressed={section === 'checks'}
        className="max-w-full whitespace-normal" onClick={() => setSection('checks')}>{knowledgeCopy.title}</Button>
    </div>
    {section === 'checks' ? <EmployeeKnowledgeChecks key={employeeId} employeeId={employeeId} /> : <>
    {selection ? (
      <Button type="button" variant="outline" className="min-h-11 max-w-full whitespace-normal" onClick={() => setSelection(undefined)}>
        {copy.assignments}
      </Button>
    ) : (
      <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
        <input type="checkbox" checked={history} className="size-4 accent-primary"
          onChange={(event) => { setHistory(event.target.checked); setOffset(0); }} />
        {copy.history}
      </label>
    )}
    {current === undefined ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p>
      : current === null ? (
        <div role="status" className="space-y-2 text-sm">
          <p>{t('trainingLog.errors.loadFailed')}</p>
          <Button type="button" variant="outline" onClick={() => {
            setResult(undefined);
            setRetry((value) => value + 1);
          }}>{t('common.retry')}</Button>
        </div>
      ) : selection ? (
        current.items[0] ? <AssignmentLearning key={selection} row={current.items[0]} />
          : <p role="status" className="text-sm text-muted-foreground">{copy.unavailable}</p>
      ) : (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold">{history ? copy.assignments : copy.current}</h4>
          {!current.items.length && <p className="text-sm text-muted-foreground">{copy.empty}</p>}
          <ul className="divide-y divide-border">
            {current.items.map((row) => (
              <li key={row.enrollment_id}>
                <button type="button" className="flex min-h-12 w-full flex-wrap items-center justify-between gap-2 py-2 text-left focus-visible:outline focus-visible:outline-ring"
                  onClick={() => setSelection(row.enrollment_id)}>
                  <span className="min-w-0 text-sm">
                    <span className="block font-medium text-primary [overflow-wrap:anywhere]">{row.course_title}</span>
                    <span className="text-xs text-muted-foreground">
                      {row.content_release_version != null && knowledgeCopy.revision + ' ' + row.content_release_version}
                      {row.enrolled_at && (row.content_release_version != null ? ' · ' : '') + copy.lastAssignment + ' ' + date(row.enrolled_at)}
                    </span>
                  </span>
                  <AssignmentStatus row={row} />
                </button>
              </li>
            ))}
          </ul>
          {current.total > PAGE_SIZE && <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">{t('trainingLog.summary.showing', { from: offset + 1, to: offset + current.items.length })}</span>
            <Button type="button" variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(offset - PAGE_SIZE)}>{t('common.back')}</Button>
            <Button type="button" variant="outline" size="sm" disabled={offset + PAGE_SIZE >= current.total} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('common.next')}</Button>
          </div>}
        </div>
      )}
    </>}
  </div>;
}

function AssignmentStatus({ row }: { row: EmployeeEnrollment }) {
  const { t } = useT();
  if (row.enrollment_status === 'cancelled' || row.computed_status === 'cancelled') return <Badge variant="outline">{t('trainingLog.history.cancelled')}</Badge>;
  if (row.enrollment_status === 'superseded' || row.computed_status === 'superseded') return <Badge variant="outline">{t('trainingLog.history.superseded')}</Badge>;
  if (row.computed_status === 'completed') return <Badge>{t('trainingLog.badge.completed')}</Badge>;
  if (row.deadline_state === 'overdue' || row.deadline_status === 'overdue') return <Badge variant="destructive">{t('trainingLog.badge.deadlineOverdue')}</Badge>;
  return <Badge variant="secondary">{row.computed_status === 'in_progress' ? t('trainingLog.badge.inProgress') : t('trainingLog.badge.assigned')}</Badge>;
}

function AssignmentLearning({ row }: { row: EmployeeEnrollment }) {
  const { t, lang } = useT();
  const copy = useEmployeeLearningCopy();
  const knowledgeCopy = useEmployeeKnowledgeCopy();
  const { text } = useLearningInsightsT();
  const answersId = useId();
  const [answersOpen, setAnswersOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const downloadRequest = useRef<AbortController | null>(null);
  useEffect(() => () => downloadRequest.current?.abort(), []);
  const deadline = row.assignment_due_at ?? row.cycle_due_at;
  const cert = row.certificate_status;
  const certificateLabel = cert === 'active' ? t('trainingLog.badge.certificateActive')
    : cert === 'expiring' ? t('trainingLog.badge.certificateExpiring')
    : cert === 'expired' ? t('trainingLog.badge.certificateExpired')
    : cert === 'revoked' ? t('trainingLog.badge.certificateRevoked') : null;
  const date = (value: string) => new Date(value).toLocaleDateString(lang);

  const download = async () => {
    if (!row.certificate_id || downloadRequest.current) return;
    const controller = new AbortController();
    downloadRequest.current = controller;
    const token = useAuthStore.getState().accessToken;
    setDownloading(true);
    try {
      const { data } = await api.get<Blob>('/v1/certificates/' + encodeURIComponent(row.certificate_id) + '/download', {
        params: { direct: true }, responseType: 'blob', signal: controller.signal,
      });
      if (controller.signal.aborted || useAuthStore.getState().accessToken !== token) return;
      const url = URL.createObjectURL(data);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'certificate-' + (row.certificate_number ?? row.certificate_id) + '.pdf';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      if (!controller.signal.aborted && useAuthStore.getState().accessToken === token) toast.error(t('certificates.downloadFailed'));
    } finally {
      if (!controller.signal.aborted) setDownloading(false);
      if (downloadRequest.current === controller) downloadRequest.current = null;
    }
  };

  return <section className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4">
    <div className="space-y-2">
      <h4 className="font-semibold [overflow-wrap:anywhere]">{row.course_title}</h4>
      <AssignmentStatus row={row} />
      {row.content_release_version != null && <span className="ml-2 text-sm text-muted-foreground">{knowledgeCopy.revision} {row.content_release_version}</span>}
      <p className="text-sm text-muted-foreground">
        {t('trainingLog.table.progress')}: {row.progress_percent}%
        {row.enrolled_at && ' · ' + copy.lastAssignment + ' ' + date(row.enrolled_at)}
        {deadline && ' · ' + t('trainingLog.table.deadline') + ' ' + date(deadline)}
      </p>
    </div>
    <div className="space-y-2 border-t border-border pt-3">
      {row.delivery_type === 'native' && <p className="text-sm">
        {copy.attempts}: {row.quiz_attempts_count}
        {row.best_score != null && ' · ' + t('trainingLog.table.score') + ' ' + row.best_score + '%'}
      </p>}
      {row.delivery_type === 'native' && row.quiz_attempts_count > 0 && (
        <Button type="button" variant="outline" className="min-h-11" aria-expanded={answersOpen} aria-controls={answersId}
          onClick={() => setAnswersOpen((open) => !open)}>{answersOpen ? copy.hideAnswers : text('answers')}</Button>
      )}
      <div id={answersId} hidden={!answersOpen}>
        {answersOpen && <LearnerAnswers inline enrollmentId={row.enrollment_id} />}
      </div>
    </div>
    <div className="space-y-2 border-t border-border pt-3">
      <h5 className="text-sm font-semibold">{t('trainingLog.table.certificate')}</h5>
      {row.certificate_number ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="[overflow-wrap:anywhere]">{row.certificate_number}</span>
            {certificateLabel && <Badge variant={cert === 'revoked' || cert === 'expired' ? 'destructive' : 'outline'}>{certificateLabel}</Badge>}
            {row.certificate_issued_at && <span>{copy.issued} {date(row.certificate_issued_at)}</span>}
            {row.certificate_expires_at && <span>{t('trainingLog.table.certificateValidUntil')} {date(row.certificate_expires_at)}</span>}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {row.certificate_id && <Button type="button" variant="outline" className="min-h-11 whitespace-normal" disabled={downloading}
              onClick={() => void download()}>{copy.download}</Button>}
            <a className="inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline"
              href={'/verify/certificate/' + encodeURIComponent(row.certificate_number)} target="_blank" rel="noopener noreferrer">{copy.verify}</a>
          </div>
        </>
      ) : <p className="text-sm text-muted-foreground">{copy.noCertificate}</p>}
    </div>
    {row.evidence_events?.length ? (
      <section className="space-y-2 border-t border-border pt-3 text-sm">
        <h5 className="font-semibold">{t('trainingLog.table.evidence')}</h5>
        <ul className="space-y-2">
          {row.evidence_events.map((event) => (
            <li key={event.event_id} className="rounded-md bg-muted/40 p-3">
              <p className="font-medium">{event.procedure_type === 'knowledge_check' ? copy.attempts : t('trainingLog.table.course')}</p>
              {event.confirmation_status !== 'not_required' && <p>{t(event.confirmation_status === 'confirmed' ? 'trainingLog.evidence.confirmed' : 'trainingLog.evidence.pending')}</p>}
              <p>{event.signed_copy_status === 'accepted' ? t('evidenceConfirmation.signedCopyAccepted')
                : event.signed_copy_status === 'uploaded_pending_review' ? t('evidenceConfirmation.signedCopyPending')
                : event.signed_copy_status === 'replacement_requested' ? t('evidenceConfirmation.signedCopyReplace', { reason: t('evidenceConfirmation.signedCopyReason') })
                : t('evidenceConfirmation.signedCopyMissing')}</p>
            </li>
          ))}
        </ul>
        <Link className="inline-flex min-h-11 items-center font-medium text-primary hover:underline" href={buildTrainingLogBrowserHref({
          filters: { user_id: row.user_id, enrollment_id: row.enrollment_id, history: true },
          search: '', returnTo: null,
        })}>{t('nav.trainingLog')}</Link>
      </section>
    ) : row.latest_evidence_event_id && row.evidence_confirmation_status && row.evidence_confirmation_status !== 'not_required' &&
      <p className="border-t border-border pt-3 text-sm">
        {t('trainingLog.table.evidence')}: {row.evidence_confirmation_status === 'confirmed'
          ? t('trainingLog.evidence.confirmed') : t('trainingLog.evidence.pending')}
      </p>}
  </section>;
}
