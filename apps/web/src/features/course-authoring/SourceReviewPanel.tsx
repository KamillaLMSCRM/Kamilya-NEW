'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { currentAuthorSession, sameAuthorSession } from './authorSession';
import { inspectCourseSource, resolveCourseSource, SourceReviewError, type SourceReviewDetails } from '@/lib/courseSourceReview';

const copy = {
  ru: { title: 'Проверка черновика', intro: 'Уроки и тесты сохранены. Замечания требуют редакторского решения, а не повторной генерации курса.',
    inspect: 'Открыть замечания и источники', busy: 'Загрузка…', dirty: 'Сначала сохраните изменения урока.',
    prepared: 'Черновик подготовлен', passed: 'Автоматическая проверка выполнена', attention: 'Автоматическая проверка оставила замечания',
    pending: 'Ожидает проверки методиста', reviewed: 'Замечания проверены для текущей версии',
    sources: 'Проверяемые источники', checked: 'Я сверил уроки и тесты с указанными версиями источников',
    reason: 'Итог проверки', rationale: 'Решение по замечанию', placeholder: 'Что проверено или исправлено — не менее 10 символов',
    confirm: 'Сохранить решения по этой версии', saved: 'Решения сохранены. Одобрение курса и публикация выполняются отдельно.',
    conflict: 'Содержание или источник изменились. Откройте проверку заново и сверьте новую версию.',
    failure: 'Не удалось получить подтверждение. Откройте проверку заново.',
    unknown: 'Результат сохранения не подтверждён. Обновите проверку, чтобы проверить историю; повторная отправка автоматически не выполняется.',
    observations: 'Дополнительные замечания автоматической проверки', history: 'История решений', noSources: 'Не удалось подтвердить версии источников. Согласование недоступно.',
    boundary: 'Сохранение решений не публикует курс и не заменяет его итоговое одобрение.' },
  kk: { title: 'Жобаны тексеру', intro: 'Сабақтар мен тесттер сақталды. Ескертулер курсқа қайта генерация жасауды емес, редактордың шешімін талап етеді.',
    inspect: 'Ескертулер мен дереккөздерді ашу', busy: 'Жүктелуде…', dirty: 'Алдымен сабақ өзгерістерін сақтаңыз.',
    prepared: 'Жоба дайын', passed: 'Автоматты тексеру аяқталды', attention: 'Автоматты тексеруде ескертулер бар',
    pending: 'Әдіскердің тексеруін күтеді', reviewed: 'Ағымдағы нұсқаның ескертулері тексерілді',
    sources: 'Тексерілетін дереккөздер', checked: 'Сабақтар мен тесттерді көрсетілген дереккөз нұсқаларымен салыстырдым',
    reason: 'Тексеру қорытындысы', rationale: 'Ескерту бойынша шешім', placeholder: 'Не тексерілгенін не түзетілгенін жазыңыз — кемінде 10 таңба',
    confirm: 'Осы нұсқа бойынша шешімдерді сақтау', saved: 'Шешімдер сақталды. Курсты мақұлдау және жариялау бөлек орындалады.',
    conflict: 'Мазмұн не дереккөз өзгерді. Тексеруді қайта ашып, жаңа нұсқаны салыстырыңыз.', failure: 'Растау алынбады. Тексеруді қайта ашыңыз.',
    unknown: 'Сақтау нәтижесі расталмады. Тарихты тексеру үшін қайта ашыңыз; автоматты қайта жіберу орындалмайды.',
    observations: 'Автоматты тексерудің қосымша ескертулері', history: 'Шешімдер тарихы', noSources: 'Дереккөз нұсқалары расталмады. Келісу қолжетімсіз.',
    boundary: 'Шешімдерді сақтау курсты жарияламайды және соңғы мақұлдауды алмастырмайды.' },
  en: { title: 'Draft review', intro: 'Lessons and tests are saved. Findings need an editorial decision, not a new course generation.',
    inspect: 'Open findings and sources', busy: 'Loading…', dirty: 'Save lesson changes first.', prepared: 'Draft prepared',
    passed: 'Automated review completed', attention: 'Automated review has findings', pending: 'Awaiting methodologist review', reviewed: 'Findings reviewed for the current version',
    sources: 'Sources to verify', checked: 'I checked the lessons and tests against these source revisions', reason: 'Review conclusion', rationale: 'Decision for this finding',
    placeholder: 'Describe what was checked or corrected — at least 10 characters', confirm: 'Save decisions for this version',
    saved: 'Decisions saved. Course approval and publication are separate actions.', conflict: 'The content or source changed. Reopen review and check the new version.',
    failure: 'Confirmation unavailable. Reopen the review.', unknown: 'Save outcome is unknown. Reload review to inspect its history; this action will not retry automatically.',
    observations: 'Additional automated observations', history: 'Decision history', noSources: 'Source revisions could not be verified. Review is unavailable.',
    boundary: 'Saving these decisions does not publish or approve the course.' },
};

const evidenceCopy = {
  ru: { target: 'Формулировка при автоматической проверке', evidence: 'Основание замечания — требует проверки',
    answers: 'Варианты, вызывающие сомнение', source: 'Фрагменты источника' },
  kk: { target: 'Автоматты тексеру кезіндегі тұжырым', evidence: 'Ескерту негізі — тексеруді қажет етеді',
    answers: 'Күмән тудырған жауаптар', source: 'Дереккөз үзінділері' },
  en: { target: 'Wording seen by the automated reviewer', evidence: 'Finding basis — requires verification',
    answers: 'Potentially competing answers', source: 'Source excerpts' },
};

export function SourceReviewPanel({ courseId, disabled, lang, onResolved }: {
  courseId: string; disabled: boolean; lang: string; onResolved: () => void;
}) {
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const sessionEpoch = useAuthStore((s) => s.sessionEpoch);
  const text = copy[lang as keyof typeof copy] ?? copy.ru;
  const evidenceText = evidenceCopy[lang as keyof typeof evidenceCopy] ?? evidenceCopy.ru;
  const identity = currentAuthorSession({ accessToken: token, user, sessionEpoch });
  const scope = `${courseId}:${identity.generation}`;
  const current = useRef(scope); current.current = scope;
  const controller = useRef<AbortController | null>(null);
  const operation = useRef(0);
  const busy = useRef(false);
  const [working, setWorking] = useState(false);
  const [state, setState] = useState<{ scope: string; details: SourceReviewDetails } | null>(null);
  const [reason, setReason] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState(false);
  const [notice, setNotice] = useState('');
  const details = state?.scope === scope ? state.details : null;

  useEffect(() => {
    operation.current += 1; controller.current?.abort(); busy.current = false;
    setWorking(false); setState(null); setReason(''); setAnswers({}); setChecked(false); setNotice('');
    return () => { operation.current += 1; controller.current?.abort(); };
  }, [scope, disabled]);

  const start = () => {
    if (busy.current || disabled || !token) return null;
    busy.current = true; setWorking(true);
    const id = ++operation.current;
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    const captured = scope;
    const isCurrent = () => current.current === captured && operation.current === id
      && sameAuthorSession(identity, currentAuthorSession({ accessToken: token, user, sessionEpoch }));
    return { signal: abort.signal, isCurrent };
  };
  const finish = (isCurrent: () => boolean) => { if (isCurrent()) { busy.current = false; setWorking(false); } };
  const inspect = async () => {
    const action = start(); if (!action) return;
    setNotice(''); setState(null); setReason(''); setAnswers({}); setChecked(false);
    try {
      const value = await inspectCourseSource(courseId, token!, action.signal);
      if (action.isCurrent()) setState({ scope, details: value });
    } catch { if (action.isCurrent()) setNotice(text.failure); }
    finally { finish(action.isCurrent); }
  };
  const validSources = Boolean(details?.source_documents.length && details.source_documents.every(
    (doc) => doc.authoritative_revision && details.available_revisions.includes(doc.authoritative_revision)));
  const canSubmit = details?.has_active_hold && validSources && checked && reason.trim().length >= 10
    && details.active_defects.every((defect) => (answers[defect.defect_id]?.trim().length ?? 0) >= 10);
  const resolve = async () => {
    if (!details || !canSubmit) return;
    const action = start(); if (!action) return;
    try {
      await resolveCourseSource(courseId, token!, action.signal, {
        reason: reason.trim(), expected_content_hash: details.content_snapshot_hash,
        verified_revision: details.source_documents[0].authoritative_revision,
        verified_revisions: Object.fromEntries(details.source_documents.map((doc) => [doc.document_id, doc.authoritative_revision])),
        defect_resolutions: details.active_defects.map((defect) => ({ defect_id: defect.defect_id,
          action: 'manual_verification_passed', rationale: answers[defect.defect_id].trim() })),
      });
      if (action.isCurrent()) { setState(null); setNotice(text.saved); onResolved(); }
    } catch (error) {
      if (action.isCurrent()) {
        setState(null); setChecked(false);
        setNotice(error instanceof SourceReviewError && error.status === 409 ? text.conflict
          : error instanceof SourceReviewError && error.unknownOutcome ? text.unknown : text.failure);
      }
    } finally { finish(action.isCurrent); }
  };

  if (!token || !['superadmin', 'methodologist'].includes(user?.role ?? '')) return null;
  return <section aria-label={text.title} className="rounded-lg border border-border bg-card p-4 space-y-4">
    <div><h2 className="font-semibold">{text.title}</h2><p className="text-sm text-muted-foreground">{text.intro}</p></div>
    {disabled && <p className="text-sm">{text.dirty}</p>}
    <Button type="button" variant="outline" disabled={disabled || working} onClick={() => void inspect()}>{working ? text.busy : text.inspect}</Button>
    {notice && <p role="status">{notice}</p>}
    {details && <>
      {details.draft_review && <ul className="text-sm space-y-1"><li>{text.prepared}</li>
        <li>{details.draft_review.self_review_status === 'passed' ? text.passed : text.attention}</li></ul>}
      <p className="font-medium">{details.has_active_hold ? text.pending : text.reviewed}</p>
      <div><h3 className="font-medium">{text.sources}</h3><ul className="text-sm">{details.source_documents.map((doc) =>
        <li key={doc.document_id}>{doc.title || doc.filename} <code className="break-all text-xs">{doc.authoritative_revision}</code></li>)}</ul></div>
      {!validSources && <p role="alert">{text.noSources}</p>}
      {details.draft_review?.observations?.length ? <details><summary>{text.observations}</summary><ul>{details.draft_review.observations.map((row) =>
        <li key={row.id} className="py-1 text-sm whitespace-pre-wrap">{row.message}</li>)}</ul></details> : null}
      {details.has_active_hold && <div className="space-y-4">
        {details.active_defects.map((defect) => <div key={defect.defect_id} className="block rounded-md border border-amber-300/50 p-3">
          <span className="block text-sm whitespace-pre-wrap">{defect.description}</span>
          {defect.target_title && <p className="mt-2 text-sm"><strong>{evidenceText.target}: </strong>{defect.target_title}</p>}
          {defect.evidence && Object.keys(defect.evidence).length > 0 && <details className="mt-2 text-sm"><summary>{evidenceText.evidence}</summary>
            {defect.evidence.observation && <p className="whitespace-pre-wrap">{defect.evidence.observation}</p>}
            {defect.evidence.missing_condition && <p className="whitespace-pre-wrap">{defect.evidence.missing_condition}</p>}
            {Boolean(defect.evidence.possible_answers?.length) && <div><p>{evidenceText.answers}</p><ul>{defect.evidence.possible_answers?.map((answer, i) => <li key={i}>{answer}</li>)}</ul></div>}
            {Boolean(defect.evidence.source_quotes?.length) && <div><p>{evidenceText.source}</p>{defect.evidence.source_quotes?.map((quote, i) => <blockquote key={i} className="border-l-2 pl-3 my-2 whitespace-pre-wrap">{quote}</blockquote>)}</div>}
          </details>}
          <label className="block text-sm font-medium mt-2">{text.rationale}
          <textarea className="mt-1 w-full rounded-md border border-input bg-background p-2 text-foreground" rows={2}
            maxLength={1000} disabled={working || disabled} placeholder={text.placeholder}
            value={answers[defect.defect_id] ?? ''} onChange={(event) => setAnswers((old) => ({ ...old, [defect.defect_id]: event.target.value }))} />
          </label>
        </div>)}
        <label className="block text-sm font-medium">{text.reason}<textarea className="mt-1 w-full rounded-md border border-input bg-background p-2 text-foreground"
          rows={2} maxLength={2000} value={reason} disabled={working || disabled} placeholder={text.placeholder} onChange={(event) => setReason(event.target.value)} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={checked} disabled={working || disabled}
          onChange={(event) => setChecked(event.target.checked)} />{text.checked}</label>
        <p className="text-sm text-muted-foreground">{text.boundary}</p>
        <Button type="button" disabled={disabled || working || !canSubmit} onClick={() => void resolve()}>{text.confirm}</Button>
      </div>}
      {details.resolutions_history.length > 0 && <details><summary>{text.history}</summary><ol>{details.resolutions_history.map((row, i) =>
        <li key={i} className="py-1 text-sm"><span>{row.resolved_at}</span> — {row.reason}</li>)}</ol></details>}
    </>}
  </section>;
}
