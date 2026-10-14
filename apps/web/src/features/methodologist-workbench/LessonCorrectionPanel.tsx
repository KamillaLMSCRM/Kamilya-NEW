'use client';

import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type ForwardedRef } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import CorrectionSources from './CorrectionSources';
import {
  applyLessonCorrection, createLessonCorrection, loadLessonCorrection, loadLessonCorrectionApplication,
  type LessonCorrectionPreview, type LessonCorrectionRequest, type CorrectionApplicationReceipt,
} from '@/lib/lessonCorrection';

export interface LessonCorrectionPanelProps {
  courseId: string;
  lessonId: string;
  lessonTitle: string;
  savedContent: string;
  dirty: boolean;
  editorBusy: boolean;
  onApplied: (receipt: CorrectionApplicationReceipt, content: string, before: string) => void;
  onApplyingChange: (busy: boolean) => void;
  onReload: () => void;
}

export interface LessonCorrectionPanelHandle {
  stageInstruction: (request: { lessonId: string; locale: 'ru' | 'kk' | 'en'; instruction: string }) => boolean;
}

type Locale = 'ru' | 'kk' | 'en';
const COPY = {
  ru: {
    title: 'AI-правка урока', instruction: 'Что изменить в уроке', prepare: 'Предложить правку',
    help: 'AI предлагает изменение только сохранённого черновика этого урока. Проверьте факты по исходным документам. После применения нужно проверить источники и тест, затем заново согласовать курс. Публикация и назначения не выполняются.',
    dirty: 'Сначала сохраните или отмените ручные изменения.', before: 'Сохранённый вариант', after: 'Предложенный вариант',
    consent: 'Я проверил правку и источники', apply: 'Применить правку к уроку', sources: 'Ссылки на источники',
    until: 'Предпросмотр действителен до', expired: 'Предпросмотр истёк. Подготовьте новую правку.',
    pending: 'Предложение ещё готовится. Проверка статуса не запускает генерацию повторно.', refresh: 'Проверить предпросмотр',
    failed: 'Предложение не подготовлено. Уточните поручение или проверьте источники.', unavailable: 'Правка недоступна или данные изменились. Подготовьте новый предпросмотр.',
    previewUnknown: 'Ответ на запрос не получен. Проверяйте тот же запрос, чтобы не запускать новую генерацию.', previewRejected: 'Запрос отклонён. Проверьте источники и уточните поручение, затем отправьте исправленный запрос.', retryPreview: 'Проверить тот же запрос',
    uncertain: 'Результат пока не подтверждён. Не создавайте новую правку: сначала проверьте результат этого подтверждения.',
    check: 'Проверить результат', retry: 'Повторить это подтверждение', applied: 'Правка применена',
    review: 'Источники и тест требуют проверки; согласование курса нужно пройти заново.',
    historical: 'Это квитанция выполненной правки, а не текущий текст урока. Последующие ручные изменения сохранены.',
    reload: 'Обновить сохранённый урок', working: 'Проверка…', identity: 'Этот план относится к другому уроку или курсу.',
    retryRestore: 'Повторить загрузку правки', restoreUnknown: 'Не удалось проверить сохранённую правку. Повторите загрузку этого же плана, прежде чем создавать новый.',
  },
  kk: {
    title: 'AI көмегімен сабақты түзету', instruction: 'Сабақта нені өзгерту керек', prepare: 'Түзету ұсыну',
    help: 'AI осы сабақтың сақталған жобасын ғана түзетуді ұсынады. Деректерді бастапқы құжаттармен салыстырыңыз. Қолданғаннан кейін дереккөздер мен тестті тексеріп, курсты қайта келісу керек. Жариялау және тағайындау орындалмайды.',
    dirty: 'Алдымен қолмен жасалған өзгерістерді сақтаңыз немесе болдырмаңыз.', before: 'Сақталған нұсқа', after: 'Ұсынылған нұсқа',
    consent: 'Түзету мен дереккөздерді тексердім', apply: 'Түзетуді сабаққа қолдану', sources: 'Дереккөз сілтемелері',
    until: 'Алдын ала қарау мерзімі', expired: 'Алдын ала қарау мерзімі аяқталды. Жаңа түзету дайындаңыз.',
    pending: 'Ұсыныс әлі дайындалуда. Күйді тексеру генерацияны қайта бастамайды.', refresh: 'Алдын ала қарауды тексеру',
    failed: 'Ұсыныс дайындалмады. Тапсырманы нақтылаңыз немесе дереккөздерді тексеріңіз.', unavailable: 'Түзету қолжетімсіз немесе деректер өзгерді. Жаңа алдын ала қарау дайындаңыз.',
    previewUnknown: 'Сұрауға жауап алынбады. Жаңа генерацияны бастамай, сол сұрауды тексеріңіз.', previewRejected: 'Сұрау қабылданбады. Дереккөздерді тексеріп, тапсырманы нақтылап, түзетілген сұрауды жіберіңіз.', retryPreview: 'Сол сұрауды тексеру',
    uncertain: 'Нәтиже әлі расталмаған. Жаңа түзету жасамай, алдымен осы растаудың нәтижесін тексеріңіз.',
    check: 'Нәтижені тексеру', retry: 'Осы растауды қайталау', applied: 'Түзету қолданылды',
    review: 'Дереккөздер мен тестті тексеріп, курсты қайта келісу керек.',
    historical: 'Бұл — орындалған түзетудің түбіртегі, сабақтың ағымдағы мәтіні емес. Кейінгі қолмен жасалған өзгерістер сақталған.',
    reload: 'Сақталған сабақты жаңарту', working: 'Тексерілуде…', identity: 'Бұл жоспар басқа сабаққа немесе курсқа тиесілі.',
    retryRestore: 'Түзетуді қайта жүктеу', restoreUnknown: 'Сақталған түзетуді тексеру мүмкін болмады. Жаңасын жасамас бұрын осы жоспарды қайта жүктеңіз.',
  },
  en: {
    title: 'AI lesson correction', instruction: 'What to change in the lesson', prepare: 'Propose correction',
    help: 'AI proposes a change to this saved draft lesson only. Check facts against the original documents. After application, review sources and the quiz, then obtain renewed course approval. Nothing is published or assigned.',
    dirty: 'Save or discard manual changes first.', before: 'Saved version', after: 'Proposed version',
    consent: 'I reviewed the correction and sources', apply: 'Apply correction to lesson', sources: 'Source references',
    until: 'Preview valid until', expired: 'The preview expired. Prepare a new correction.',
    pending: 'The proposal is still pending. Checking status does not generate it again.', refresh: 'Check preview',
    failed: 'No proposal is ready. Clarify the instruction or check the sources.', unavailable: 'The correction is unavailable or its context changed. Prepare a new preview.',
    previewUnknown: 'The request response was lost. Check the same request instead of starting a new generation.', previewRejected: 'The request was refused. Check the sources and clarify the instruction, then submit a corrected request.', retryPreview: 'Check the same request',
    uncertain: 'The result is not confirmed yet. Check this confirmation before creating a new correction.',
    check: 'Check result', retry: 'Retry this confirmation', applied: 'Correction applied',
    review: 'Sources and the quiz require review; course approval must be renewed.',
    historical: 'This is a receipt for a past correction, not the current lesson text. Later manual changes are preserved.',
    reload: 'Reload saved lesson', working: 'Checking…', identity: 'This plan belongs to a different lesson or course.',
    retryRestore: 'Retry loading correction', restoreUnknown: 'The saved correction could not be checked. Reload this same plan before creating another.',
  },
} as const;

const localeOf = (lang: string): Locale => lang === 'kk' || lang === 'en' ? lang : 'ru';
const cancelled = (cause: unknown) => cause instanceof Error && ['AbortError', 'CanceledError'].includes(cause.name);
const httpFailure = (cause: unknown): { response?: { status?: number; data?: { detail?: unknown; error?: unknown; message?: unknown } } } =>
  cause && typeof cause === 'object' ? cause : {};
const structuredPreviewRefusal = (cause: unknown) => {
  const response = httpFailure(cause).response;
  const data = response?.data;
  return Boolean(response && typeof response.status === 'number' && response.status >= 400 && response.status < 500
    && data && [data.detail, data.error, data.message].some((value) => typeof value === 'string' && value.trim().length > 0));
};

function rememberPlan(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set('correction_plan', id); else url.searchParams.delete('correction_plan');
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
}

export default forwardRef<LessonCorrectionPanelHandle, LessonCorrectionPanelProps>(function LessonCorrectionPanel(props, ref) {
  const user = useAuthStore((state) => state.user);
  const token = useAuthStore((state) => state.accessToken);
  if (process.env.NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED !== 'true'
    || process.env.NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED !== 'true'
    || user?.role !== 'methodologist' || user.impersonated_by || !token) return null;
  return <Panel key={`${token}:${user.user_id}:${user.tenant_id}:${props.courseId}:${props.lessonId}`} {...props} handleRef={ref} />;
});

function Panel(props: LessonCorrectionPanelProps & { handleRef: ForwardedRef<LessonCorrectionPanelHandle> }) {
  const locale = localeOf(useLanguageStore((state) => state.lang));
  const localeRef = useRef(locale); localeRef.current = locale;
  const ui = COPY[locale];
  const propsRef = useRef(props); propsRef.current = props;
  const uiRef = useRef(ui); uiRef.current = ui;
  const [instruction, setInstruction] = useState('');
  const [preview, setPreview] = useState<LessonCorrectionPreview | null>(null);
  const [receipt, setReceipt] = useState<CorrectionApplicationReceipt | null>(null);
  const [attempt, setAttempt] = useState<LessonCorrectionRequest | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [invalidated, setInvalidated] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [now, setNow] = useState(Date.now());
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const activeWrite = useRef(false);
  const operationPending = useRef(false);
  const unresolvedPreview = useRef(false);
  const unresolvedApplication = useRef(false);
  const previewContext = useRef<{ state: LessonCorrectionPreview['state']; locale: Locale } | null>(null);
  const instructionRef = useRef<HTMLTextAreaElement>(null);

  const begin = () => {
    controller.current?.abort();
    const signal = new AbortController(); controller.current = signal;
    const current = ++epoch.current; operationPending.current = true; setPending(true); setError(null);
    return { signal: signal.signal, current };
  };
  const currentOperation = (current: number) => mounted.current && current === epoch.current;
  const finish = (current: number) => {
    if (!currentOperation(current)) return;
    operationPending.current = false;
    setPending(false);
    if (activeWrite.current) { activeWrite.current = false; propsRef.current.onApplyingChange(false); }
  };
  const verifyPreview = (value: LessonCorrectionPreview, preparedLocale = localeRef.current) => {
    if (value.lesson_id !== propsRef.current.lessonId) throw new Error('Correction target mismatch');
    unresolvedPreview.current = false;
    previewContext.current = { state: value.state, locale: preparedLocale };
    const stale = value.state === 'ready' && (preparedLocale !== localeRef.current || value.before_content !== propsRef.current.savedContent);
    setPreview(value); setReviewed(false); setInvalidated(stale); setAttempt(null); rememberPlan(value.plan_id);
    if (stale) setError(uiRef.current.unavailable);
  };
  const acceptReceipt = (value: CorrectionApplicationReceipt, confirmed?: LessonCorrectionPreview) => {
    if (value.lesson_id !== propsRef.current.lessonId || value.course_id !== propsRef.current.courseId) throw new Error('Correction target mismatch');
    if (confirmed && (value.plan_id !== confirmed.plan_id || value.revision !== confirmed.revision || value.fingerprint !== confirmed.fingerprint)) throw new Error('Correction seal mismatch');
    unresolvedPreview.current = false; unresolvedApplication.current = false;
    previewContext.current = null;
    setReceipt(value); setUncertain(false); setError(null); setAttempt(null); rememberPlan(value.plan_id);
    const latest = propsRef.current;
    if (confirmed?.proposal && confirmed.before_content !== null && !latest.dirty
      && !latest.editorBusy && latest.savedContent === confirmed.before_content) {
      latest.onApplied(value, confirmed.proposal.content, confirmed.before_content);
    }
    setPreview(null);
  };

  useImperativeHandle(props.handleRef, () => ({
    stageInstruction(request) {
      const latest = propsRef.current;
      if (!mounted.current || operationPending.current || activeWrite.current || unresolvedPreview.current || unresolvedApplication.current
        || previewContext.current?.state === 'pending'
        || latest.dirty || latest.editorBusy || request.lessonId !== latest.lessonId || request.locale !== localeRef.current || locale !== localeRef.current
        || typeof request.instruction !== 'string' || !request.instruction.trim() || Array.from(request.instruction).length > 4000) return false;
      controller.current?.abort(); const stagedEpoch = ++epoch.current;
      previewContext.current = null;
      setInstruction(request.instruction); setPreview(null); setReceipt(null); setAttempt(null);
      setReviewed(false); setInvalidated(false); setError(null); setUncertain(false); rememberPlan(null);
      // Defer focus until the chat dialog has closed/restored its prior focus.
      window.setTimeout(() => {
        if (!currentOperation(stagedEpoch) || locale !== localeRef.current) return;
        instructionRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
        instructionRef.current?.focus();
      }, 0);
      return true;
    },
  }), [locale]);

  const restore = async (id: string) => {
    if (operationPending.current) return;
    unresolvedApplication.current = true;
    const operation = begin();
    try {
      const applied = await loadLessonCorrectionApplication(id, operation.signal);
      if (!currentOperation(operation.current)) return;
      if (applied) acceptReceipt(applied);
      else {
        const loaded = await loadLessonCorrection(id, operation.signal);
        if (currentOperation(operation.current)) { verifyPreview(loaded); unresolvedApplication.current = false; }
      }
    } catch (cause) {
      if (currentOperation(operation.current) && !cancelled(cause)) setError(uiRef.current.restoreUnknown);
    } finally { finish(operation.current); }
  };

  useEffect(() => {
    mounted.current = true;
    const id = new URLSearchParams(window.location.search).get('correction_plan');
    if (id) void restore(id);
    return () => {
      mounted.current = false; controller.current?.abort(); epoch.current += 1; operationPending.current = false;
      if (activeWrite.current) { activeWrite.current = false; propsRef.current.onApplyingChange(false); }
    };
    // Identity changes remount Panel. This mount-only restore is also StrictMode-safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setNow(Date.now());
    if (preview?.state !== 'ready') return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [preview]);

  const previous = useRef({ locale, dirty: props.dirty, savedContent: props.savedContent });
  useEffect(() => {
    const changed = previous.current.locale !== locale || previous.current.savedContent !== props.savedContent;
    const dirtyChanged = previous.current.dirty !== props.dirty;
    previous.current = { locale, dirty: props.dirty, savedContent: props.savedContent };
    if (!changed && !dirtyChanged) return;
    setReviewed(false);
    if (activeWrite.current || uncertain || receipt || unresolvedApplication.current || unresolvedPreview.current || previewContext.current?.state === 'pending') return;
    if (props.dirty) { setInvalidated(true); return; }
    controller.current?.abort(); epoch.current += 1; operationPending.current = false; unresolvedPreview.current = false; setPending(false);
    previewContext.current = null;
    setPreview(null); setAttempt(null); setError(null); setInvalidated(false); rememberPlan(null);
  }, [locale, props.dirty, props.savedContent, uncertain, receipt]);

  const create = async (body?: LessonCorrectionRequest) => {
    if (pending || uncertain || props.dirty || props.editorBusy || (!body && !instruction.trim())) return;
    if (!body && (unresolvedPreview.current || unresolvedApplication.current || previewContext.current?.state === 'pending')) return;
    const request = body ?? { request_key: crypto.randomUUID(), lesson_id: props.lessonId, instruction, locale };
    const operation = begin(); unresolvedPreview.current = true; previewContext.current = null; setReceipt(null); setPreview(null); setReviewed(false); setAttempt(request);
    try {
      const result = await createLessonCorrection(request, operation.signal);
      if (currentOperation(operation.current)) verifyPreview(result, request.locale);
    } catch (cause) {
      if (currentOperation(operation.current) && !cancelled(cause)) {
        if (structuredPreviewRefusal(cause)) {
          unresolvedPreview.current = false;
          setAttempt(null);
          setError(uiRef.current.previewRejected);
        } else setError(uiRef.current.previewUnknown);
      }
    } finally { finish(operation.current); }
  };

  const refreshPreview = async () => {
    if (!preview || pending) return;
    const preparedLocale = previewContext.current?.locale ?? localeRef.current;
    const operation = begin();
    try {
      const result = await loadLessonCorrection(preview.plan_id, operation.signal);
      if (currentOperation(operation.current)) verifyPreview(result, preparedLocale);
    } catch (cause) {
      if (currentOperation(operation.current) && !cancelled(cause)) { setInvalidated(true); setError(uiRef.current.unavailable); }
    } finally { finish(operation.current); }
  };

  const expired = Boolean(preview && Date.parse(preview.expires_at) <= now);
  const canApply = Boolean(preview?.state === 'ready' && preview.fingerprint && preview.proposal
    && preview.before_content === props.savedContent && !invalidated && !expired && reviewed && !props.dirty && !props.editorBusy);
  const checkResult = async (retry = false) => {
    if (!preview || pending || (retry && !canApply)) return;
    const confirmed = preview; const operation = begin();
    try {
      const applied = await loadLessonCorrectionApplication(confirmed.plan_id, operation.signal);
      if (!currentOperation(operation.current)) return;
      if (applied) acceptReceipt(applied, confirmed);
      else if (retry) {
        finish(operation.current);
        await apply(confirmed);
      } else setError(uiRef.current.uncertain);
    } catch (cause) {
      if (currentOperation(operation.current) && !cancelled(cause)) setError(uiRef.current.uncertain);
    } finally { finish(operation.current); }
  };

  const apply = async (confirmed = preview) => {
    if (!confirmed || !confirmed.fingerprint || !canApply || activeWrite.current) return;
    const operation = begin(); activeWrite.current = true; props.onApplyingChange(true);
    try {
      const applied = await applyLessonCorrection({ plan_id: confirmed.plan_id, revision: confirmed.revision, fingerprint: confirmed.fingerprint }, operation.signal);
      if (currentOperation(operation.current)) acceptReceipt(applied, confirmed);
    } catch (cause) {
      if (!currentOperation(operation.current) || cancelled(cause)) return;
      unresolvedApplication.current = true; setUncertain(true);
      try {
        const applied = await loadLessonCorrectionApplication(confirmed.plan_id, operation.signal);
        if (!currentOperation(operation.current)) return;
        if (applied) acceptReceipt(applied, confirmed);
        else {
          const failed = httpFailure(cause).response;
          if (failed && failed.status && failed.status < 500 && failed.data?.detail !== 'correction_application_busy') {
            unresolvedApplication.current = false;
            setUncertain(false); setInvalidated(true); setReviewed(false); setError(uiRef.current.unavailable);
          } else setError(uiRef.current.uncertain);
        }
      } catch { if (currentOperation(operation.current)) setError(uiRef.current.uncertain); }
    } finally { finish(operation.current); }
  };

  const recoveryBlocked = Boolean(attempt || preview?.state === 'pending' || unresolvedApplication.current);
  return <Card className="min-w-0 border-primary/30">
    <CardHeader><CardTitle>{ui.title}</CardTitle><p className="text-sm">{props.lessonTitle}</p><p className="text-sm text-muted-foreground">{ui.help}</p></CardHeader>
    <CardContent className="min-w-0 space-y-4">
      {props.dirty && <p role="status" className="text-sm text-amber-700">{ui.dirty}</p>}
      <label className="block text-sm font-medium">{ui.instruction}<textarea ref={instructionRef} className="mt-2 w-full rounded border p-2" rows={3} maxLength={4000} value={instruction} disabled={pending || uncertain || recoveryBlocked} onChange={(event) => {
        if (operationPending.current || unresolvedPreview.current || unresolvedApplication.current || previewContext.current?.state === 'pending' || uncertain) return;
        controller.current?.abort(); epoch.current += 1; operationPending.current = false; unresolvedPreview.current = false; setPending(false); setInstruction(event.target.value);
        previewContext.current = null;
        setPreview(null); setReceipt(null); setAttempt(null); setReviewed(false); setInvalidated(false); setError(null); rememberPlan(null);
      }} /></label>
      <Button type="button" onClick={() => void create()} disabled={pending || uncertain || recoveryBlocked || props.dirty || props.editorBusy || !instruction.trim()}>{ui.prepare}</Button>
      {unresolvedApplication.current && !uncertain && <Button type="button" variant="outline" disabled={pending} onClick={() => {
        const id = new URLSearchParams(window.location.search).get('correction_plan');
        if (id) void restore(id);
      }}>{ui.retryRestore}</Button>}
      {attempt && !preview && !receipt && <Button type="button" variant="outline" disabled={pending || props.dirty || props.editorBusy} onClick={() => void create(attempt)}>{ui.retryPreview}</Button>}
      {pending && <p role="status" aria-live="polite" className="text-sm">{ui.working}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {preview?.state === 'pending' && <div className="space-y-2"><p role="status">{ui.pending}</p><Button type="button" variant="outline" disabled={pending} onClick={() => void refreshPreview()}>{ui.refresh}</Button></div>}
      {preview?.state === 'failed' && <p role="status">{ui.failed}</p>}
      {preview?.state === 'ready' && preview.proposal && <div className="min-w-0 space-y-3">
        <div className="grid min-w-0 gap-3 xl:grid-cols-2">{[[ui.before, preview.before_content], [ui.after, preview.proposal.content]].map(([title, content]) => <section key={title!} className="min-w-0"><h3 className="mb-2 font-medium">{title}</h3><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded border p-3 font-sans text-sm">{content}</pre></section>)}</div>
        <details className="min-w-0 text-sm"><summary className="cursor-pointer font-medium">{ui.sources} ({preview.proposal.citations.length})</summary><CorrectionSources key={`${preview.plan_id}:${preview.revision}:${preview.fingerprint}:${locale}`} citations={preview.proposal.citations} locale={locale} /></details>
        <p className="text-sm">{ui.until}: {new Date(preview.expires_at).toLocaleString({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[locale])}</p>
        {expired && <p role="status" className="text-sm text-amber-700">{ui.expired}</p>}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reviewed} disabled={pending || invalidated || props.dirty} onChange={(event) => setReviewed(event.target.checked)} />{ui.consent}</label>
        {!uncertain && <Button type="button" disabled={pending || !canApply} onClick={() => void apply()}>{ui.apply}</Button>}
        {uncertain && <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={pending} onClick={() => void checkResult()}>{ui.check}</Button><Button type="button" disabled={pending || !canApply} onClick={() => void checkResult(true)}>{ui.retry}</Button></div>}
      </div>}
      {receipt && <div role="status" aria-live="polite" className="space-y-2 rounded border border-primary/40 p-3 text-sm"><h3 className="font-medium">{ui.applied}</h3><p>{ui.review}</p><p>{ui.historical}</p><p className="break-all">{receipt.plan_id} · {new Date(receipt.applied_at).toLocaleString({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[locale])}</p><Button type="button" variant="outline" disabled={props.editorBusy} onClick={props.onReload}>{ui.reload}</Button></div>}
    </CardContent>
  </Card>;
}
