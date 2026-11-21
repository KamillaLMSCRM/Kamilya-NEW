'use client';

import { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import {
  DecisionPracticePlayer, practiceCopy, validDecisionPractice,
  type DecisionPractice, type PracticeLanguage, type PracticeStep,
} from './DecisionPractice';

type State = { practice: DecisionPractice | null; revision: string | null };
const emptyText = () => ({ ru: '', kk: '' });
const emptyStep = (): PracticeStep => ({ id: crypto.randomUUID(), text: emptyText(), choices: [] });

function emptyPractice(): DecisionPractice {
  const [first, left, right] = Array.from({ length: 3 }, emptyStep);
  first.choices = [left, right].map(step => ({ label: emptyText(), target: step.id }));
  return { title: emptyText(), steps: [first, left, right] };
}

export function DecisionPracticeEditor({ courseId, lessonId, lang, disabled, onDirtyChange, onSaved }: {
  courseId: string; lessonId: string; lang: string; disabled: boolean;
  onDirtyChange: (dirty: boolean) => void; onSaved: () => void;
}) {
  const copy = practiceCopy(lang);
  const path = `/v1/courses/${courseId}/lessons/${lessonId}/decision-practice/editor`;
  const [opened, setOpened] = useState(false);
  const [saved, setSaved] = useState<State | null>(null);
  const [draft, setDraft] = useState<DecisionPractice | null>(null);
  const [language, setLanguage] = useState<PracticeLanguage>(lang === 'kk' ? 'kk' : 'ru');
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<'saved' | 'failed' | 'conflict'>();
  const dirty = Boolean(saved && JSON.stringify(draft) !== JSON.stringify(saved.practice));
  const valid = draft !== null && validDecisionPractice(draft);

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  function receive(result: State) {
    setSaved(result);
    setDraft(result.practice);
    setPreview(false);
  }

  async function load() {
    setOpened(true);
    setStatus(undefined);
    setBusy(true);
    try { receive((await api.get<State>(path)).data); }
    catch { setStatus('failed'); }
    finally { setBusy(false); }
  }

  async function save(practice: DecisionPractice | null) {
    if (!saved || busy || disabled) return;
    setBusy(true);
    setStatus(undefined);
    try {
      receive((await api.put<State>(path, { practice, revision: saved.revision })).data);
      setStatus('saved');
      onSaved();
    } catch (error) {
      setStatus(isAxiosError(error) && error.response?.status === 409 ? 'conflict' : 'failed');
    } finally { setBusy(false); }
  }

  function updateStep(index: number, transform: (step: PracticeStep) => PracticeStep) {
    setDraft(current => current && ({ ...current, steps: current.steps.map((step, i) => i === index ? transform(step) : step) }));
  }

  const short = (step: PracticeStep, index: number) =>
    `${copy.step} ${index + 1}${step.text[language].trim() ? ' · ' + step.text[language].trim().slice(0, 48) : ''}`;

  if (!opened) return <Button className="self-start" type="button" variant="outline" onClick={() => void load()}>{copy.edit}</Button>;

  return <section className="min-w-0 space-y-4 rounded-xl border border-border p-4" aria-label={copy.name}>
    <h3 className="font-semibold">{copy.name}</h3>
    {busy && <p role="status">{copy.loading}</p>}
    {status && <p role={status === 'saved' ? 'status' : 'alert'}>{copy[status]}</p>}
    {(!saved || status === 'conflict') && !busy &&
      <Button type="button" variant="outline" onClick={() => { if (!dirty || window.confirm(copy.reload + '?')) void load(); }}>{copy.reload}</Button>}
    {saved && !draft && <Button type="button" disabled={disabled || busy} onClick={() => setDraft(emptyPractice())}>{copy.create}</Button>}
    {draft && <>
      <label className="block w-fit text-sm">{copy.language}
        <select className="ml-2 min-h-10 rounded-md border border-input bg-background px-2"
          value={language} onChange={event => setLanguage(event.target.value === 'kk' ? 'kk' : 'ru')}>
          <option value="ru">Русский</option>
          <option value="kk">Қазақша</option>
        </select>
      </label>
      {preview ? <DecisionPracticePlayer practice={draft} language={language} /> :
        <fieldset disabled={disabled || busy} className="min-w-0 space-y-4">
          <label className="block text-sm">{copy.title}
            <Input maxLength={180} value={draft.title[language]} onChange={event =>
              setDraft({ ...draft, title: { ...draft.title, [language]: event.target.value } })} />
          </label>
          {draft.steps.map((step, index) => <fieldset className="min-w-0 space-y-3 rounded-lg border p-3" key={step.id}>
            <legend className="px-1 text-sm font-medium">{copy.step} {index + 1}</legend>
            <label className="block text-sm">{step.choices.length ? copy.text : copy.ending}
              <textarea className="mt-1 min-h-24 w-full rounded-md border border-input bg-background p-2" maxLength={2500}
                value={step.text[language]} onChange={event => updateStep(index, item =>
                  ({ ...item, text: { ...item.text, [language]: event.target.value } }))} />
            </label>
            {step.choices.map((choice, i) => <div key={i} className="grid min-w-0 gap-2 sm:grid-cols-2">
              <label className="min-w-0 text-sm">{copy.answer} {i + 1}
                <Input maxLength={180} value={choice.label[language]} onChange={event => updateStep(index, item =>
                  ({ ...item, choices: item.choices.map((value, at) => at === i
                    ? { ...value, label: { ...value.label, [language]: event.target.value } } : value) }))} />
              </label>
              <label className="min-w-0 text-sm">{copy.target} {i + 1}
                <select className="block min-h-10 w-full min-w-0 rounded-md border border-input bg-background px-2" value={choice.target}
                  onChange={event => updateStep(index, item => ({ ...item, choices: item.choices.map((value, at) =>
                    at === i ? { ...value, target: event.target.value } : value) }))}>
                  <option value="">{copy.target}</option>
                  {draft.steps.map((target, stepIndex) => target.id === step.id || stepIndex === 0
                    ? null : <option key={target.id} value={target.id}>{short(target, stepIndex)}</option>)}
                </select>
              </label>
              <Button className="justify-self-start" type="button" size="sm" variant="ghost"
                onClick={() => updateStep(index, item => ({ ...item, choices: item.choices.filter((_, at) => at !== i) }))}>
                {copy.remove}
              </Button>
            </div>)}
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" disabled={step.choices.length >= 4}
                onClick={() => updateStep(index, item => ({ ...item, choices: [...item.choices, { label: emptyText(), target: '' }] }))}>
                {copy.addChoice}
              </Button>
              {index > 0 && draft.steps.length > 3 && <Button type="button" size="sm" variant="ghost"
                onClick={() => setDraft({ ...draft, steps: draft.steps.filter(item => item.id !== step.id).map(item => ({
                  ...item, choices: item.choices.map(choice => choice.target === step.id ? { ...choice, target: '' } : choice),
                })) })}>{copy.remove} {copy.step.toLowerCase()}</Button>}
            </div>
          </fieldset>)}
          <Button type="button" size="sm" variant="outline" disabled={draft.steps.length >= 12}
            onClick={() => setDraft({ ...draft, steps: [...draft.steps, emptyStep()] })}>{copy.addStep}</Button>
        </fieldset>}
      {dirty && !valid && <p className="text-sm text-muted-foreground">{copy.invalid}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={disabled || busy || !valid || !dirty || status === 'conflict'}
          onClick={() => void save(draft)}>{copy.save}</Button>
        <Button type="button" variant="outline" disabled={!preview && !valid}
          onClick={() => setPreview(!preview)}>{preview ? copy.back : copy.preview}</Button>
        {dirty && <Button type="button" variant="ghost" disabled={busy}
          onClick={() => { setDraft(saved?.practice ?? null); setPreview(false); }}>{copy.cancel}</Button>}
        {saved?.practice && !dirty && <Button type="button" variant="ghost" disabled={disabled || busy}
          onClick={() => { if (window.confirm(copy.confirmDelete)) void save(null); }}>{copy.delete}</Button>}
      </div>
    </>}
  </section>;
}
