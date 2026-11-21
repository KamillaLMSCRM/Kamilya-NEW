'use client';

import { useCallback, useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { type CourseLanguage } from './courseLanguages';
import {
  captionTime, parseCaptionTime, practicePath, videoPracticeCopy,
  type PracticeCopy, type PracticeState, type VideoClip, type VideoPractice,
} from './videoPractice';
import { useYoutubeTiming, youtubeFrameProps } from './useYoutubeTiming';

const languages = { ru: 'Русский', kk: 'Қазақша' } as const;

function VideoPracticePreview({ clip, lang, locked, onPick }: {
  clip: VideoClip; lang: CourseLanguage; locked: boolean; onPick: (seconds: number) => void;
}) {
  const copy = videoPracticeCopy(lang);
  const src = 'https://www.youtube-nocookie.com/embed/' + clip.video_id + '?start=' + clip.start + '&end=' + clip.end + '&playsinline=1';
  const { frame, frameUrl, playback, unavailable } = useYoutubeTiming(src);
  const seconds = playback ? Math.floor(playback.seconds) : null;
  const canPick = seconds !== null && seconds > clip.start && seconds < clip.end;

  return <div className="min-w-0 space-y-2">
    <iframe ref={frame} title={copy.preview} src={frameUrl} {...youtubeFrameProps} />
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-muted-foreground">{captionTime(clip.start)}–{captionTime(clip.end)}</p>
      <Button size="sm" type="button" variant="outline" disabled={locked || !canPick}
        onClick={() => { if (canPick) onPick(seconds); }}>{copy.pickCurrent}</Button>
    </div>
    {unavailable && <p className="text-sm text-muted-foreground">{copy.timingUnavailable}</p>}
  </div>;
}

function complete({ question, choices, explanation }: PracticeCopy) {
  return question.trim() && explanation.trim() && choices.every(choice => choice.trim())
    && new Set(choices.map(choice => choice.trim().toLowerCase())).size === choices.length;
}

export function VideoPracticeEditor({ courseId, lessonId, lang, disabled }: {
  courseId: string; lessonId: string; lang: CourseLanguage; disabled: boolean;
}) {
  const [state, setState] = useState<PracticeState>();
  const [draft, setDraft] = useState<VideoPractice | null>(null);
  const [moment, setMoment] = useState('');
  const [language, setLanguage] = useState<'ru' | 'kk'>(lang === 'kk' ? 'kk' : 'ru');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [subtitleFile, setSubtitleFile] = useState<File | null>(null);
  const [subtitleError, setSubtitleError] = useState(false);
  const copy = videoPracticeCopy(lang);
  const path = practicePath(courseId, lessonId) + '/editor';

  const receive = (result: PracticeState) => {
    const next = result.approved ?? result.proposal?.draft ?? null;
    setState(result);
    setDraft(next);
    setMoment(next ? captionTime(next.at) : '');
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

  const perform = async (operation: () => Promise<{ data: PracticeState } | undefined>) => {
    setBusy(true);
    setFailed(false);
    try {
      const response = await operation();
      if (response) receive(response.data);
    }
    catch (error) {
      const detail = isAxiosError(error) ? error.response?.data?.detail : undefined;
      if (detail === 'captions_invalid') setSubtitleError(true);
      else if (detail === 'provider_unavailable') setState(current => current && { ...current, error: detail });
      else setFailed(true);
    }
    finally { setBusy(false); }
  };

  const clip = state?.clip;
  if (!clip && !failed) return null;
  const locked = disabled || busy || !!state?.pending;
  const at = parseCaptionTime(moment);
  const validTime = clip && at !== null && clip.start < at && at < clip.end;
  const message = {
    captions_unavailable: copy.unavailable, no_caption_evidence: copy.noSource,
    provider_blocked: copy.blocked, provider_timeout: copy.timeout, provider_unavailable: copy.unavailable,
    transcript_unavailable: copy.unavailable, language_unavailable: copy.unavailable,
    video_unavailable: copy.unavailable, video_too_long: copy.unavailable,
    transcript_too_large: copy.unavailable, transcript_too_short: copy.noSource,
    proposal_not_grounded: copy.invalid,
    invalid_proposal: copy.invalid, outcome_unknown: copy.unknown,
  }[state?.error ?? ''];
  const save = (value: VideoPractice | null) => void perform(() => api.put(path, {
    revision: state?.revision, clip, practice: value,
  }));
  const add = () => {
    const empty = (): PracticeCopy => ({ question: '', choices: ['', '', ''], explanation: '' });
    setDraft({ at: 0, correct_index: 0, ru: empty(), kk: empty() });
    setMoment('');
  };
  const generateFromFile = () => {
    if (!subtitleFile) return;
    setSubtitleError(false);
    void perform(async () => {
      const subtitles = await subtitleFile.text().catch(() => '');
      if (!subtitles.trim() || subtitles.length > 500000) {
        setSubtitleError(true);
        return;
      }
      return api.post(path + '/propose', { subtitles });
    });
  };

  const unedited = !draft || (state?.approved === draft && moment === captionTime(draft.at));

  return <section className="space-y-3 rounded-xl border border-border p-4">
    <h3 className="font-semibold">{copy.title}</h3>
    {state?.approved && <p className="text-sm text-success">{copy.approved}</p>}
    {(failed || state?.pending || message) && <div role="status" className="space-y-2 text-sm">
      <p>{failed ? copy.error : message || copy.pending}</p>
      {(failed || state?.pending) && <Button size="sm" type="button" variant="outline"
        onClick={() => void load()} disabled={busy}>{copy.refresh}</Button>}
    </div>}
    {clip && unedited && !state?.pending && <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {!draft && <Button type="button" disabled={locked} onClick={add}>{copy.add}</Button>}
        <Button type="button" variant="outline" disabled={locked}
          onClick={() => void perform(() => api.post(path + '/propose'))}>{copy.prepare}</Button>
        {draft && state?.proposal && <Button type="button" variant="outline" disabled={locked}
          onClick={() => {
            const proposal = state.proposal?.draft;
            if (proposal) {
              setDraft(proposal);
              setMoment(captionTime(proposal.at));
            }
          }}>{copy.useProposal}</Button>}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 max-w-full text-sm">{copy.subtitleFile}
          <Input type="file" className="mt-1 max-w-full" accept=".srt,.vtt" disabled={locked} onChange={event => {
            const file = event.target.files?.[0];
            const invalid = !!file && (!/\.(srt|vtt)$/i.test(file.name) || file.size > 2000000);
            setSubtitleFile(invalid ? null : file ?? null);
            setSubtitleError(invalid);
          }} />
        </label>
        <Button type="button" variant="outline" disabled={locked || !subtitleFile}
          onClick={generateFromFile}>{copy.fileQuestion}</Button>
      </div>
    </div>}
    {subtitleError && <p role="alert" className="text-sm text-destructive">{copy.invalidFile}</p>}
    {draft && clip && <>
      <div className="grid gap-4 xl:grid-cols-2 xl:items-start">
        <VideoPracticePreview clip={clip} lang={lang} locked={locked} onPick={seconds => setMoment(captionTime(seconds))} />
        <fieldset disabled={locked} className="min-w-0 space-y-3">
          {state?.proposal && <p className="text-sm text-muted-foreground">
            {copy.evidence} · {captionTime(state.proposal.draft.at)}<br />{state.proposal.evidence}
          </p>}
          <label className="block space-y-1 text-sm">{copy.moment}
            <Input type="text" inputMode="text" placeholder="0:00" value={moment}
              onChange={event => setMoment(event.target.value)} aria-invalid={!!moment && !validTime} />
          </label>
          {!!moment && !validTime && <p className="text-sm text-destructive">{copy.invalidTime}</p>}
          <label className="block space-y-1 text-sm">{copy.chooseLanguage}
            <select value={language} onChange={event => setLanguage(event.target.value === 'kk' ? 'kk' : 'ru')}
              className="block h-10 rounded-md border border-input bg-background px-2">
              {Object.entries(languages).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
            </select>
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
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={locked || !validTime || !complete(draft.ru) || !complete(draft.kk)}
          onClick={() => { if (validTime) save({ ...draft, at }); }}>{copy.save}</Button>
        {state?.approved
          ? <Button type="button" disabled={locked} variant="outline" onClick={() => save(null)}>{copy.remove}</Button>
          : <Button type="button" disabled={locked} variant="outline" onClick={() => setDraft(null)}>{copy.cancel}</Button>}
      </div>
    </>}
  </section>;
}
