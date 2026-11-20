'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { type CourseLanguage } from './courseLanguages';
import { captionTime, practicePath, videoPracticeCopy, type PracticeState, type VideoPractice } from './videoPractice';

const languages = { ru: 'Русский', kk: 'Қазақша' } as const;

export function VideoPracticeEditor({ courseId, lessonId, lang, disabled }: {
  courseId: string; lessonId: string; lang: CourseLanguage; disabled: boolean;
}) {
  const [state, setState] = useState<PracticeState>();
  const [draft, setDraft] = useState<VideoPractice | null>(null);
  const [language, setLanguage] = useState<'ru' | 'kk'>(lang === 'kk' ? 'kk' : 'ru');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const copy = videoPracticeCopy(lang);
  const path = practicePath(courseId, lessonId) + '/editor';

  const receive = (result: PracticeState) => {
    setState(result);
    setDraft(result.approved ?? result.proposal?.draft ?? null);
  };
  const load = useCallback(async (signal?: AbortSignal) => {
    setFailed(false);
    try {
      const { data } = await api.get<PracticeState>(path, { signal });
      if (!signal?.aborted) receive(data);
    } catch {
      if (!signal?.aborted) setFailed(true);
    }
  }, [path]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const perform = async (operation: () => Promise<{ data: PracticeState }>) => {
    setBusy(true);
    setFailed(false);
    try { receive((await operation()).data); }
    catch { setFailed(true); }
    finally { setBusy(false); }
  };
  if (!state?.clip && !failed) return null;

  const locked = disabled || busy || !!state?.pending;
  const message = {
    captions_unavailable: copy.unavailable, no_caption_evidence: copy.noSource,
    invalid_proposal: copy.invalid, outcome_unknown: copy.unknown,
  }[state?.error ?? ''];
  const save = (value: VideoPractice | null) => void perform(() => api.put(path, {
    revision: state?.revision, clip: state?.clip, practice: value,
  }));
  return <section className="space-y-3 rounded-xl border border-border p-4">
    <h3 className="font-semibold">{copy.title}</h3>
    {state?.approved && <p className="text-sm text-success">{copy.approved}</p>}
    {(failed || state?.pending || message) && <div role="status" className="space-y-2 text-sm">
      <p>{failed ? copy.error : message || copy.pending}</p>
      {(failed || state?.pending) && <Button size="sm" type="button" variant="outline"
        onClick={() => void load()} disabled={busy}>{copy.refresh}</Button>}
    </div>}
    {state?.clip && !draft && !state.pending && <Button type="button" variant="outline" disabled={locked}
      onClick={() => void perform(() => api.post(path + '/propose'))}>{copy.prepare}</Button>}
    {draft && <>
      {state?.proposal && <p className="text-sm text-muted-foreground">
        {copy.evidence} · {captionTime(state.proposal.draft.at)}<br />{state.proposal.evidence}
      </p>}
      <fieldset disabled={locked} className="space-y-3">
        <label className="block space-y-1 text-sm">{copy.chooseLanguage}
          <select value={language} onChange={event => setLanguage(event.target.value === 'kk' ? 'kk' : 'ru')}
            className="block h-10 rounded-md border border-input bg-background px-2">
            {Object.entries(languages).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </select>
        </label>
        <label className="block space-y-1 text-sm">{copy.moment}
          <Input type="number" min={(state?.clip?.start ?? 0) + 1} max={(state?.clip?.end ?? 0) - 1}
            value={draft.at} onChange={event => setDraft({ ...draft, at: Number(event.target.value) })} />
        </label>
        <label className="block space-y-1 text-sm">{copy.question}
          <Input maxLength={500} value={draft[language].question}
            onChange={event => setDraft({ ...draft, [language]: { ...draft[language], question: event.target.value } })} />
        </label>
        {draft[language].choices.map((choice, index) => <label key={index} className="block space-y-1 text-sm">
          {copy.option} {index + 1}
          <Input maxLength={240} value={choice} onChange={event => {
            const choices: VideoPractice['ru']['choices'] = [...draft[language].choices];
            choices[index] = event.target.value;
            setDraft({ ...draft, [language]: { ...draft[language], choices } });
          }} />
        </label>)}
        <label className="block space-y-1 text-sm">{copy.correct}
          <select value={draft.correct_index} onChange={event => setDraft({ ...draft, correct_index: Number(event.target.value) })}
            className="block h-10 rounded-md border border-input bg-background px-2">
            {[0, 1, 2].map(index => <option key={index} value={index}>{index + 1}</option>)}
          </select>
        </label>
        <label className="block space-y-1 text-sm">{copy.explanation}
          <Input maxLength={500} value={draft[language].explanation}
            onChange={event => setDraft({ ...draft, [language]: { ...draft[language], explanation: event.target.value } })} />
        </label>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={locked || !state?.clip || draft.at <= state.clip.start || draft.at >= state.clip.end}
          onClick={() => save(draft)}>{copy.save}</Button>
        {state?.approved && <Button type="button" disabled={locked} variant="outline" onClick={() => save(null)}>{copy.remove}</Button>}
      </div>
    </>}
  </section>;
}
