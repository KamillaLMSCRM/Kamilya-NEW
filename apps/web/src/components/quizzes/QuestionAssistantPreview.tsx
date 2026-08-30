'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, LoaderCircle, Sparkles } from 'lucide-react';

import { Badge, Button } from '@/components/ui';
import { EDITOR_ASSISTANT_INTENTS, EditorAssistantIntent, EditorAssistantPatchOperation, EditorAssistantPreviewApiError, EditorAssistantPreviewResponse, requestQuestionAssistantPreview } from '@/lib/editorAssistant';

interface QuestionAssistantPreviewProps { quizId: string; questionId: string; isDirty?: boolean; disabledReason?: string; }
interface SubmissionIdentity { signature: string; requestKey: string; previewKey: string; }

const INTENT_LABELS: Record<EditorAssistantIntent, string> = {
  rewrite_wording: 'Переписать вопрос', add_context: 'Добавить контекст', regenerate_distractors: 'Обновить неверные варианты', balance_answer_length: 'Выровнять длину ответов', add_or_rewrite_explanation: 'Переписать пояснение',
};
const FIELD_LABELS: Record<EditorAssistantPatchOperation['field_path'], string> = { 'question.text': 'Текст вопроса', 'question.answer_options': 'Варианты ответа', 'question.explanation': 'Пояснение' };
const APPLICABILITY_COPY: Record<EditorAssistantPreviewResponse['applicability'], string> = {
  applicable: 'Предложение можно проверить ниже.', applicable_with_warnings: 'Предложение содержит замечания: проверьте их ниже.',
  requires_new_draft_revision: 'Сначала сохраните новую редакцию вопроса, затем запросите предложение снова.', not_applicable: 'Помощник не может применить выбранную задачу к этому вопросу или его исходным материалам.', stale: 'Вопрос изменился. Обновите сохранённую версию и запросите предложение повторно.',
};

function TextValue({ value }: { value: string | null }) { return <p className="mt-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-sm leading-5 text-foreground">{value ?? 'Не указано'}</p>; }
function AnswerOptions({ value }: { value: Extract<EditorAssistantPatchOperation['after_value'], Array<unknown>> }) {
  return <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm leading-5 text-foreground">{value.map((option, index) => <li key={index} className="break-words [overflow-wrap:anywhere]"><span>{option.text}</span>{option.is_correct && <span className="ml-2 inline-flex rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800">Правильный ответ</span>}</li>)}</ol>;
}
function PatchValue({ value }: { value: EditorAssistantPatchOperation['after_value'] }) { return typeof value === 'string' || value === null ? <TextValue value={value} /> : <AnswerOptions value={value} />; }

export function QuestionAssistantPreview({ quizId, questionId, isDirty = false, disabledReason = 'Сначала сохраните изменения вопроса, пояснения или вариантов ответа, затем сформируйте предложение.' }: QuestionAssistantPreviewProps) {
  const [instruction, setInstruction] = useState('');
  const [intent, setIntent] = useState<EditorAssistantIntent>('rewrite_wording');
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<EditorAssistantPreviewResponse | null>(null);
  const [error, setError] = useState<EditorAssistantPreviewApiError | null>(null);
  const identityRef = useRef<SubmissionIdentity | null>(null);
  const requestSequenceRef = useRef(0);

  const invalidate = () => { requestSequenceRef.current += 1; identityRef.current = null; setLoading(false); setPreview(null); setError(null); };
  useEffect(() => {
    if (!isDirty) return;
    requestSequenceRef.current += 1;
    identityRef.current = null;
    setLoading(false);
    setPreview(null);
    setError(null);
  }, [isDirty]);
  const handleInstructionChange = (value: string) => { setInstruction(value); invalidate(); };
  const handleIntentChange = (value: EditorAssistantIntent) => { setIntent(value); invalidate(); };
  const handleSubmit = async () => {
    const normalizedInstruction = instruction.trim();
    if (!normalizedInstruction || loading || isDirty) return;
    const signature = `${quizId}:${questionId}:${intent}:${normalizedInstruction}`;
    if (identityRef.current?.signature !== signature) identityRef.current = { signature, requestKey: crypto.randomUUID(), previewKey: crypto.randomUUID() };
    const identity = identityRef.current;
    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    setLoading(true); setPreview(null); setError(null);
    try {
      const result = await requestQuestionAssistantPreview(quizId, questionId, { request_key: identity.requestKey, preview_key: identity.previewKey, intent, instruction: normalizedInstruction });
      if (requestSequenceRef.current === requestSequence) setPreview(result);
    } catch (requestError) {
      if (requestSequenceRef.current !== requestSequence) return;
      setError(requestError instanceof EditorAssistantPreviewApiError ? requestError : new EditorAssistantPreviewApiError('Не удалось связаться с помощником.', null, null));
    } finally { if (requestSequenceRef.current === requestSequence) setLoading(false); }
  };
  const disabled = loading || isDirty || !instruction.trim();
  return <section aria-labelledby="question-assistant-heading" className="rounded-xl border border-primary/20 bg-primary/[0.035] p-4 sm:p-5">
    <div className="flex items-start gap-3"><div className="mt-0.5 rounded-lg bg-primary/10 p-2 text-primary" aria-hidden="true"><Sparkles className="h-4 w-4" /></div><div className="min-w-0 flex-1"><h3 id="question-assistant-heading" className="font-semibold text-foreground">Помощник по вопросу</h3><p className="mt-1 break-words [overflow-wrap:anywhere] text-sm leading-5 text-muted-foreground">Выберите задачу и опишите, что улучшить. Помощник подготовит только предложение для проверки.</p></div><Badge variant="secondary" className="shrink-0 bg-background text-muted-foreground">Предпросмотр</Badge></div>
    <fieldset className="mt-4"><legend className="text-sm font-medium text-foreground">Задача помощнику</legend><div className="mt-2 flex flex-wrap gap-2">{EDITOR_ASSISTANT_INTENTS.map((item) => <button key={item} type="button" aria-pressed={intent === item} disabled={isDirty} onClick={() => handleIntentChange(item)} className="rounded-full border border-primary/30 px-3 py-1.5 text-xs font-medium text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-50 aria-[pressed=true]:bg-primary aria-[pressed=true]:text-primary-foreground">{INTENT_LABELS[item]}</button>)}</div></fieldset>
    <label className="mt-4 block space-y-2"><span className="text-sm font-medium text-foreground">Инструкция помощнику</span><textarea value={instruction} onChange={(event) => handleInstructionChange(event.target.value)} disabled={isDirty} className="min-h-24 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm leading-5 text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60" placeholder="Например: сделайте формулировку короче для новых сотрудников" aria-describedby="question-assistant-hint" /></label>
    <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"><p id="question-assistant-hint" className="break-words [overflow-wrap:anywhere] text-xs text-muted-foreground">{isDirty ? disabledReason : 'Помощник не применяет предложение автоматически и не получает несохранённые изменения.'}</p><Button type="button" variant="outline" className="w-full border-primary/30 text-primary sm:w-auto" disabled={disabled} onClick={handleSubmit} aria-label="Сформировать предложение помощника">{loading ? <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}{loading ? 'Готовим предложение…' : 'Сформировать предложение'}</Button></div>
    <div className="mt-4" aria-live="polite" aria-busy={loading}>{loading && <p className="rounded-lg border border-border bg-background p-3 text-sm text-muted-foreground">Помощник анализирует вопрос и исходные материалы…</p>}{error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3"><div className="flex gap-2 text-sm font-medium text-destructive"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span className="break-words [overflow-wrap:anywhere]">{error.message}</span></div>{error.safeDetail && <p className="mt-2 break-words [overflow-wrap:anywhere] text-xs text-muted-foreground">{error.safeDetail}</p>}</div>}
      {preview && preview.state !== 'pending' && preview.applicability !== 'applicable' && <p className="rounded-lg border border-border bg-background p-3 text-sm text-muted-foreground break-words [overflow-wrap:anywhere]">{APPLICABILITY_COPY[preview.applicability]}</p>}
      {preview?.state === 'pending' && <p className="mt-3 rounded-lg border border-border bg-background p-3 text-sm text-muted-foreground">Предложение принято в обработку. Ничего не применено.</p>}
      {preview?.state === 'failed' && <div role="alert" className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3"><p className="text-sm font-medium text-destructive">Помощник не смог подготовить безопасное предложение.</p><p className="mt-2 break-words [overflow-wrap:anywhere] text-xs text-muted-foreground">{preview.failure?.message}</p></div>}
      {preview?.state === 'completed' && <div className="mt-3 space-y-3"><div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 text-sm text-emerald-800"><CheckCircle2 className="h-4 w-4 shrink-0" /><span>Предложение готово. Ничего не применено к вопросу.</span></div>{preview.operations.map((operation) => <article key={operation.field_path} className="rounded-lg border border-border bg-background p-3"><h4 className="text-sm font-semibold text-foreground">{FIELD_LABELS[operation.field_path]}</h4><div className="mt-3 grid gap-3 md:grid-cols-2"><div><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Сейчас</p><PatchValue value={operation.before_value} /></div><div className="rounded-md bg-primary/5 p-2.5"><p className="text-xs font-medium uppercase tracking-wide text-primary">Предложение</p><PatchValue value={operation.after_value} /></div></div></article>)}{preview.validation && <div className="rounded-lg border border-border bg-background p-3"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-foreground">Проверка качества</span><Badge variant="secondary">{preview.validation.status === 'pass' ? 'Проверка пройдена' : preview.validation.status === 'warn' ? 'Есть замечания' : 'Предложение заблокировано'}</Badge></div><ul className="mt-2 space-y-1 text-sm text-muted-foreground">{preview.validation.issues.map((issue, index) => <li key={`${issue.code}-${index}`} className="break-words [overflow-wrap:anywhere]">{issue.blocking ? 'Важно: ' : ''}{issue.message}</li>)}</ul></div>}</div>}</div>
  </section>;
}
