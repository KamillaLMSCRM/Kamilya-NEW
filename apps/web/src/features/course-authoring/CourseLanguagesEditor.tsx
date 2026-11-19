'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { contentLanguages, isCourseLanguage, type CourseLanguage } from './courseLanguages';

type Policy = { primary: CourseLanguage; requested: CourseLanguage[] };
type Edition = { content: Record<string, string>; approved: boolean; pending: boolean };
type Editor = { policy: Policy | null; source_sha256: string; source: Record<string, string>; editions: Partial<Record<CourseLanguage, Edition>> };

export function CourseLanguagesEditor({ courseId, prepare = false }: { courseId: string; prepare?: boolean }) {
  const ui = useLanguageStore(s => s.lang);
  const scope = useAuthStore(s => `${s.user?.tenant_id}:${s.user?.user_id}:${s.user?.role}`);
  return <EditionEditor key={`${scope}:${courseId}`} courseId={courseId} prepare={prepare} ui={ui} />;
}

function EditionEditor({ courseId, prepare, ui }: { courseId: string; prepare: boolean; ui: string }) {
  const kk = ui === 'kk';
  const en = ui === 'en';
  const label = (ru: string, k: string, e: string) => kk ? k : en ? e : ru;
  const path = `/v1/courses/${courseId}/languages/editor`;
  const [open, setOpen] = useState(prepare);
  const [editor, setEditor] = useState<Editor>();
  const [primary, setPrimary] = useState<CourseLanguage>('ru');
  const [requested, setRequested] = useState<CourseLanguage[]>(['ru', 'kk']);
  const [target, setTarget] = useState<CourseLanguage>();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  const attempted = useRef(new Set<string>());

  useEffect(() => {
    if (!open) return;
    let current = true;
    void api.get<Editor>(path).then(({ data }) => {
      if (!current) return;
      setEditor(data);
      if (data.policy) {
        setPrimary(data.policy.primary);
        setRequested(data.policy.requested);
        setTarget(data.policy.requested.find(language => language !== data.policy?.primary));
      }
    }).catch(() => { if (current) setError(true); });
    return () => { current = false; };
  }, [open, path]);

  useEffect(() => {
    setDraft(target ? editor?.editions[target]?.content ?? {} : {});
    setPending(Boolean(target && editor?.editions[target]?.pending));
  }, [editor, target]);

  async function generate(language: CourseLanguage) {
    setError(false);
    setBusy(true);
    try {
      const { data } = await api.post<{ content: Record<string, string>; pending: boolean; error?: string }>(
        `${path}/${language}/generate`,
      );
      setDraft(data.content);
      setPending(data.pending);
      setError(Boolean(data.error));
    } catch { setError(true); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (!prepare || !editor?.policy || !target || editor.editions[target] || busy) return;
    const key = `${editor.source_sha256}:${target}`;
    if (attempted.current.has(key)) return;
    attempted.current.add(key);
    void generate(target);
    // One automatic request for each course revision and language.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prepare, editor, target, busy]);

  async function configure() {
    setBusy(true);
    setError(false);
    try {
      await api.put(path, { primary, requested });
      const { data } = await api.get<Editor>(path);
      setEditor(data);
      setTarget(requested.find(language => language !== primary));
    } catch { setError(true); }
    finally { setBusy(false); }
  }

  async function save(approve: boolean) {
    if (!editor || !target) return;
    setBusy(true);
    setError(false);
    try {
      await api.put(`${path}/${target}`, { source_sha256: editor.source_sha256, content: draft, approve });
      setEditor({ ...editor, editions: { ...editor.editions, [target]: { content: draft, approved: approve, pending: false } } });
    } catch { setError(true); }
    finally { setBusy(false); }
  }

  const approved = Boolean(target && editor?.editions[target]?.approved);
  const fields = Object.entries(editor?.source ?? {});
  const complete = fields.length > 0 && fields.every(([key]) => draft[key]?.trim());
  return (
    <details open={open} onToggle={event => setOpen(event.currentTarget.open)}
      className="min-w-0 rounded-2xl border border-border bg-card p-4 shadow-sm">
      <summary className="cursor-pointer font-semibold">{label('Языки курса', 'Курс тілдері', 'Course languages')}</summary>
      {open && <div className="mt-4 space-y-4">
        {error && <p role="alert" className="text-sm text-destructive">{label('Не удалось выполнить действие. Проверьте редакцию и поля перевода.', 'Әрекет орындалмады. Нұсқаны және аударма өрістерін тексеріңіз.', 'The action failed. Check the revision and translated fields.')}</p>}
        {!editor && !error && <p role="status">{label('Загрузка…', 'Жүктелуде…', 'Loading…')}</p>}
        {editor && <fieldset disabled={busy} className="space-y-3">
          <label className="flex flex-wrap items-center gap-2 text-sm">
            {label('Исходный язык', 'Түпнұсқа тілі', 'Original language')}
            <select value={primary} disabled={Boolean(editor.policy)} className="rounded-lg border bg-background p-2"
              onChange={event => {
                const language = event.target.value;
                if (isCourseLanguage(language)) {
                  setPrimary(language);
                  setRequested(current => current.includes(language) ? current : [...current, language]);
                }
              }}>
              {Object.entries(contentLanguages).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap gap-4">
            {Object.entries(contentLanguages).map(([value, name]) => isCourseLanguage(value) &&
              <label key={value} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={requested.includes(value)} disabled={value === primary}
                  onChange={event => setRequested(current => event.target.checked ? [...current, value] : current.filter(locale => locale !== value))} />
                {name}
              </label>)}
          </div>
          <Button type="button" variant="outline" onClick={() => void configure()}>{label('Сохранить языки', 'Тілдерді сақтау', 'Save languages')}</Button>
        </fieldset>}
        {editor?.policy && editor.policy.requested.length > 1 && <label className="flex flex-wrap items-center gap-2 text-sm">
          {label('Редакция перевода', 'Аударма нұсқасы', 'Translation edition')}
          <select value={target} onChange={event => { if (isCourseLanguage(event.target.value)) setTarget(event.target.value); }}
            disabled={busy} className="rounded-lg border bg-background p-2">
            {editor.policy.requested.filter(language => language !== editor.policy?.primary).map(language =>
              <option key={language} value={language}>{contentLanguages[language]}</option>)}
          </select>
        </label>}
        {target && <div className="space-y-3">
          {approved
            ? <p role="status" className="text-sm font-medium text-success">{label('Языковая версия утверждена', 'Тілдік нұсқа бекітілді', 'Language edition approved')}</p>
            : <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" disabled={busy || pending} onClick={() => void generate(target)}>
                  {label('Подготовить перевод', 'Аударма дайындау', 'Generate translation')}
                </Button>
                <Button type="button" variant="outline" disabled={!complete || busy} onClick={() => void save(false)}>{label('Сохранить черновик', 'Жобаны сақтау', 'Save draft')}</Button>
                <Button type="button" disabled={!complete || busy} onClick={() => void save(true)}>{label('Утвердить перевод', 'Аударманы бекіту', 'Approve translation')}</Button>
              </div>}
          {(pending || busy) && <p className="text-sm text-muted-foreground" role="status">
            {label('Ожидается результат перевода. Можно подготовить свою редакцию.', 'Аударма нәтижесі күтілуде. Өз нұсқаңызды дайындауға болады.', 'Translation result is pending. You can prepare an edition manually.')}
          </p>}
          {!approved && <div className="divide-y divide-border">
            {fields.map(([key, source], index) => <div key={key} className="grid gap-3 py-3 md:grid-cols-2">
              <div className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted/35 p-3 text-sm">{source}</div>
              <textarea aria-label={label(`Перевод ${index + 1}`, `Аударма ${index + 1}`, `Translation ${index + 1}`)}
                rows={source.length > 160 ? 5 : 2} value={draft[key] ?? ''} disabled={busy}
                onChange={event => setDraft(current => ({ ...current, [key]: event.target.value }))}
                className="min-w-0 rounded-lg border border-border bg-background p-3 text-sm" />
            </div>)}
          </div>}
        </div>}
      </div>}
    </details>
  );
}
