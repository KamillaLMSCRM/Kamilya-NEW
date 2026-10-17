'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import {
  getRuntimeSettings,
  getRuntimeSettingsHistory,
  revertRuntimeSettings,
  RuntimeSetting,
  RuntimeSettingValue,
  RuntimeSettingsHistoryEntry,
  RuntimeSettingsRequestError,
  RuntimeSettingsSnapshot,
  updateRuntimeSettings,
} from '@/lib/adminRuntimeSettings';

type Language = 'ru' | 'kk' | 'en';

const copy: Record<Language, Record<string, string>> = {
  en: {
    title: 'Runtime settings', subtitle: 'Allowlisted operational parameters for the next operation.',
    search: 'Filter settings', loading: 'Loading…', retry: 'Retry', save: 'Save changes', reset: 'Reset to default',
    reason: 'Reason for change (required)', reasonPlaceholder: 'Explain why this operational value is changing',
    noChanges: 'No changes to save.', noSettings: 'No settings match this filter.', defaults: 'Default', range: 'Allowed range',
    reasonTooShort: 'Enter at least 3 characters.', reasonTooLong: 'Use no more than 240 characters.', invalidNumber: 'Enter a valid number within the allowed range.',
    next: 'Takes effect on the next operation. In-flight operations keep their original values.',
    history: 'History', noHistory: 'No changes recorded yet.', revert: 'Revert', revertPrompt: 'Reason for reverting (required)',
    revertConfirm: 'Revert this snapshot?', conflict: 'The settings changed in another session. The latest values were loaded; your draft was preserved.',
    saved: 'Runtime settings saved.', reverted: 'Runtime settings reverted.', loadError: 'Could not load runtime settings.',
    saveError: 'Could not save runtime settings.', historyError: 'Could not load runtime settings history.', revertError: 'Could not revert runtime settings.',
    forbidden: 'Only an authorised superadmin can change runtime settings.', overridden: 'Overridden', modelNote: 'Saving does not test model availability and cannot change endpoints, order, or reserve activation.', validationHelp: 'Check the value and any related settings, then save again.',
  },
  ru: {
    title: 'Параметры выполнения', subtitle: 'Разрешённые операционные параметры для следующей операции.',
    search: 'Фильтр параметров', loading: 'Загрузка…', retry: 'Повторить', save: 'Сохранить изменения', reset: 'Вернуть значение по умолчанию',
    reason: 'Причина изменения (обязательно)', reasonPlaceholder: 'Объясните изменение операционного значения',
    noChanges: 'Нет изменений для сохранения.', noSettings: 'Параметры не найдены.', defaults: 'По умолчанию', range: 'Допустимый диапазон',
    reasonTooShort: 'Введите не менее 3 символов.', reasonTooLong: 'Используйте не более 240 символов.', invalidNumber: 'Введите корректное число в допустимом диапазоне.',
    next: 'Вступает в силу со следующей операции. Текущие операции сохраняют исходные значения.',
    history: 'История', noHistory: 'Изменений пока нет.', revert: 'Вернуть', revertPrompt: 'Причина возврата (обязательно)',
    revertConfirm: 'Вернуть этот снимок?', conflict: 'Параметры изменены в другой сессии. Загружены последние значения, черновик сохранён.',
    saved: 'Параметры выполнения сохранены.', reverted: 'Параметры выполнения возвращены.', loadError: 'Не удалось загрузить параметры.',
    saveError: 'Не удалось сохранить параметры.', historyError: 'Не удалось загрузить историю.', revertError: 'Не удалось вернуть параметры.',
    forbidden: 'Изменять параметры может только авторизованный супер-администратор.', overridden: 'Переопределено', modelNote: 'Сохранение не проверяет доступность модели и не меняет endpoint, порядок или активацию резерва.', validationHelp: 'Проверьте значение и связанные параметры, затем сохраните снова.',
  },
  kk: {
    title: 'Орындау параметрлері', subtitle: 'Келесі операцияға арналған рұқсат етілген операциялық параметрлер.',
    search: 'Параметрлерді сүзу', loading: 'Жүктелуде…', retry: 'Қайталау', save: 'Өзгерістерді сақтау', reset: 'Әдепкіге қайтару',
    reason: 'Өзгерту себебі (міндетті)', reasonPlaceholder: 'Операциялық мәннің неге өзгеретінін түсіндіріңіз',
    noChanges: 'Сақтайтын өзгеріс жоқ.', noSettings: 'Сүзгіге сәйкес параметр жоқ.', defaults: 'Әдепкі', range: 'Рұқсат етілген ауқым',
    reasonTooShort: 'Кемінде 3 таңба енгізіңіз.', reasonTooLong: '240 таңбадан артық енгізбеңіз.', invalidNumber: 'Рұқсат етілген ауқымдағы дұрыс санды енгізіңіз.',
    next: 'Келесі операцияда күшіне енеді. Ағымдағы операциялар бастапқы мәндерін сақтайды.',
    history: 'Тарих', noHistory: 'Әзірге өзгеріс жоқ.', revert: 'Қайтару', revertPrompt: 'Қайтару себебі (міндетті)',
    revertConfirm: 'Осы нұсқаны қайтару керек пе?', conflict: 'Параметрлер басқа сессияда өзгерді. Соңғы мәндер жүктелді, жоба сақталды.',
    saved: 'Орындау параметрлері сақталды.', reverted: 'Орындау параметрлері қайтарылды.', loadError: 'Параметрлерді жүктеу мүмкін болмады.',
    saveError: 'Параметрлерді сақтау мүмкін болмады.', historyError: 'Тарихты жүктеу мүмкін болмады.', revertError: 'Параметрлерді қайтару мүмкін болмады.',
    forbidden: 'Орындау параметрлерін тек рұқсаты бар супер-әкімші өзгерте алады.', overridden: 'Қайта анықталған', modelNote: 'Сақтау модельдің қолжетімділігін тексермейді және endpoint, реттілік немесе резервті іске қосуды өзгертпейді.', validationHelp: 'Мәнді және байланысты параметрлерді тексеріп, қайта сақтаңыз.',
  },
};

function displayValue(value: RuntimeSettingValue | null | undefined): string {
  if (value === true) return 'true';
  if (value === false) return 'false';
  return value === null || value === undefined ? '—' : String(value);
}

function parseValue(setting: RuntimeSetting, raw: string | boolean): RuntimeSettingValue | null {
  if (setting.kind === 'boolean') return Boolean(raw);
  if (setting.kind === 'integer' || setting.kind === 'number') {
    const rawText = String(raw).trim();
    if (!rawText) return null;
    const value = Number(rawText);
    return Number.isFinite(value) ? value : null;
  }
  return String(raw);
}

function settingGroup(key: string): string {
  const prefix = key.split('.')[0];
  return prefix ? prefix.toLowerCase() : 'other';
}

function changedHistoryValues(entry: RuntimeSettingsHistoryEntry): string[] {
  const keys = new Set([...Object.keys(entry.before), ...Object.keys(entry.after)]);
  return [...keys].filter((key) => JSON.stringify(entry.before[key]) !== JSON.stringify(entry.after[key])).map((key) => `${key}: ${displayValue(entry.before[key] as RuntimeSettingValue)} → ${displayValue(entry.after[key] as RuntimeSettingValue)}`);
}

export function RuntimeSettingsControl() {
  const { lang } = useT();
  const token = useAuthStore((state) => state.accessToken);
  const text = copy[(lang as Language) in copy ? lang as Language : 'en'];
  const [snapshot, setSnapshot] = useState<RuntimeSettingsSnapshot | null>(null);
  const [history, setHistory] = useState<RuntimeSettingsHistoryEntry[]>([]);
  const [draft, setDraft] = useState<Record<string, RuntimeSettingValue | null>>({});
  const [filter, setFilter] = useState('');
  const [reason, setReason] = useState('');
  const [revertReason, setRevertReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const generation = useRef(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const load = useCallback(async (preserveDraft = true) => {
    const requestToken = token;
    const requestGeneration = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await getRuntimeSettings();
      if (requestGeneration !== generation.current) return;
      setSnapshot(next);
      if (!preserveDraft) setDraft({});
    } catch (cause) {
      if (requestGeneration !== generation.current || tokenRef.current !== requestToken) return;
      setError(cause instanceof RuntimeSettingsRequestError && cause.status === 403 ? text.forbidden : text.loadError);
    } finally {
      if (requestGeneration === generation.current && tokenRef.current === requestToken) setLoading(false);
    }
  }, [text.forbidden, text.loadError, token]);

  useEffect(() => {
    generation.current += 1;
    setSnapshot(null); setHistory([]); setDraft({}); setReason(''); setRevertReason(''); setConflict(false); setSaving(false); setHistoryLoading(false);
    if (token) void load(false); else setLoading(false);
  }, [load, token]);

  const loadHistory = useCallback(async () => {
    const requestGeneration = generation.current;
    setHistoryLoading(true);
    try {
      const nextHistory = await getRuntimeSettingsHistory();
      if (requestGeneration === generation.current && tokenRef.current === token) setHistory(nextHistory);
    } catch {
      if (requestGeneration === generation.current && tokenRef.current === token) setError(text.historyError);
    } finally {
      if (requestGeneration === generation.current && tokenRef.current === token) setHistoryLoading(false);
    }
  }, [text.historyError, token]);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const visibleSettings = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return (snapshot?.settings ?? []).filter((setting) => !query || `${setting.key} ${setting.label}`.toLowerCase().includes(query));
  }, [filter, snapshot]);

  const changed = Object.keys(draft).filter((key) => draft[key] !== undefined);

  const setValue = (setting: RuntimeSetting, value: string | boolean) => {
    if (saving || loading) return;
    const parsed = parseValue(setting, value);
    if (parsed === null) { setError(text.invalidNumber); return; }
    setDraft((current) => ({ ...current, [setting.key]: parsed }));
    setStatus(null);
  };

  const resetValue = (setting: RuntimeSetting) => {
    if (saving || loading) return;
    setDraft((current) => ({ ...current, [setting.key]: null }));
    setStatus(null);
  };

  const save = async () => {
    if (!snapshot || saving) return;
    const requestToken = token;
    const requestGeneration = generation.current;
    const isCurrentRequest = () => tokenRef.current === requestToken && generation.current === requestGeneration;
    if (!changed.length) { setStatus(text.noChanges); return; }
    if (reason.trim().length < 3) { setError(text.reasonTooShort); return; }
    if (reason.trim().length > 240) { setError(text.reasonTooLong); return; }
    setSaving(true); setError(null); setConflict(false);
    try {
      const next = await updateRuntimeSettings(snapshot.revision, Object.fromEntries(changed.map((key) => [key, draft[key]])), reason.trim());
      if (!isCurrentRequest()) return;
      setSnapshot(next); setDraft({}); setReason(''); setStatus(text.saved); await loadHistory();
    } catch (cause) {
      if (tokenRef.current !== requestToken) return;
      if (cause instanceof RuntimeSettingsRequestError && cause.status === 409) {
        setConflict(true); await load(true);
      } else if (cause instanceof RuntimeSettingsRequestError && cause.code) setError(`${text.saveError} (${cause.code}). ${text.validationHelp}`);
      else setError(text.saveError);
    } finally { if (tokenRef.current === requestToken) setSaving(false); }
  };

  const revert = async (entry: RuntimeSettingsHistoryEntry) => {
    if (!snapshot || saving || revertReason.trim().length < 3) { setError(text.reasonTooShort); return; }
    if (revertReason.trim().length > 240) { setError(text.reasonTooLong); return; }
    if (!confirm(text.revertConfirm)) return;
    const requestToken = token;
    const requestGeneration = generation.current;
    const isCurrentRequest = () => tokenRef.current === requestToken && generation.current === requestGeneration;
    setSaving(true); setError(null);
    try {
      const next = await revertRuntimeSettings(snapshot.revision, entry.revision, revertReason.trim());
      if (!isCurrentRequest()) return;
      setSnapshot(next); setDraft({}); setRevertReason(''); setStatus(text.reverted); await loadHistory();
    } catch (cause) {
      if (tokenRef.current !== requestToken) return;
      if (cause instanceof RuntimeSettingsRequestError && cause.status === 409) { setConflict(true); await load(true); }
      else if (cause instanceof RuntimeSettingsRequestError && cause.code) setError(`${text.revertError} (${cause.code}). ${text.validationHelp}`);
      else setError(text.revertError);
    } finally { if (tokenRef.current === requestToken) setSaving(false); }
  };

  return (
    <section className="space-y-6" aria-labelledby="runtime-settings-title">
      <Card>
        <CardHeader>
          <CardTitle><span id="runtime-settings-title">{text.title}</span></CardTitle>
          <p className="text-sm text-text-secondary">{text.subtitle}</p>
          <p className="text-xs text-text-tertiary">{snapshot ? `Revision: ${snapshot.revision}` : text.loading}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? <p role="status">{text.loading}</p> : error && !snapshot ? <div className="space-y-3"><p role="alert">{error}</p><Button type="button" variant="secondary" onClick={() => void load(false)}>{text.retry}</Button></div> : (
            <>
              {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
              {conflict && <p className="text-sm text-destructive" role="alert">{text.conflict}</p>}
              {status && <p className="text-sm text-text-secondary" role="status">{status}</p>}
              <p className="text-xs text-text-tertiary">{text.next}</p>
              <p className="text-xs text-text-tertiary">{text.modelNote}</p>
              <label className="block text-sm font-medium" htmlFor="runtime-settings-filter">{text.search}</label>
              <Input id="runtime-settings-filter" value={filter} onChange={(event) => setFilter(event.target.value)} />
              <div className="space-y-4">
                {visibleSettings.length === 0 ? <p className="text-sm text-text-secondary">{text.noSettings}</p> : visibleSettings.map((setting) => {
                  const value = draft[setting.key] === null ? setting.default : (draft[setting.key] ?? setting.value);
                  const isReset = draft[setting.key] === null;
                  return <div key={setting.key} className="rounded-md border p-4 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium">{setting.label}</p><p className="text-xs text-text-tertiary">{setting.key} · {settingGroup(setting.key)}</p></div>{setting.overridden && <span className="text-xs text-text-secondary">{text.overridden}</span>}</div>
                    {setting.kind === 'boolean' ? <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(value)} onChange={(event) => setValue(setting, event.target.checked)} disabled={saving || loading} />{displayValue(value)}</label> : setting.choices?.length ? <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={String(value)} onChange={(event) => setValue(setting, event.target.value)} aria-label={setting.label} disabled={saving || loading}>{setting.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select> : <Input aria-label={setting.label} type={setting.kind === 'model' ? 'text' : 'number'} value={String(value)} onChange={(event) => setValue(setting, event.target.value)} min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} step={setting.kind === 'integer' ? 1 : 'any'} disabled={saving || loading} />}
                    <p className="text-xs text-text-tertiary">{text.defaults}: {displayValue(setting.default)}{setting.minimum !== null && setting.minimum !== undefined ? ` · ${text.range}: ${setting.minimum}–${setting.maximum ?? '∞'}` : ''}</p>
                    <Button type="button" variant="secondary" onClick={() => resetValue(setting)} disabled={saving || isReset}>{text.reset}</Button>
                  </div>;
                })}
              </div>
              <label className="block text-sm font-medium" htmlFor="runtime-settings-reason">{text.reason}</label>
              <Input id="runtime-settings-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder={text.reasonPlaceholder} minLength={3} maxLength={240} disabled={saving || loading} />
              <Button type="button" onClick={() => void save()} disabled={saving || loading || changed.length === 0 || reason.trim().length < 3 || reason.trim().length > 240}>{saving ? text.loading : text.save}</Button>
            </>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>{text.history}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <Input aria-label={text.revertPrompt} value={revertReason} onChange={(event) => setRevertReason(event.target.value)} placeholder={text.revertPrompt} minLength={3} maxLength={240} disabled={saving || loading} />
          {historyLoading ? <p role="status">{text.loading}</p> : <div className="space-y-3">{[
            ...(history.some((entry) => entry.revision === 1) ? [] : [{ revision: 1, before: {}, after: {}, reason: text.defaults, created_at: '', actor_id: null } as RuntimeSettingsHistoryEntry]),
            ...history,
          ].map((entry) => <div key={entry.revision} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"><div><p className="font-medium">#{entry.revision}</p><p className="text-sm text-text-secondary">{entry.reason}</p>{changedHistoryValues(entry).map((change) => <p key={change} className="text-xs text-text-tertiary">{change}</p>)}{entry.created_at && <p className="text-xs text-text-tertiary">{entry.created_at}</p>}</div><Button type="button" variant="secondary" onClick={() => void revert(entry)} disabled={saving || loading || revertReason.trim().length < 3 || revertReason.trim().length > 240}>{text.revert}</Button></div>)}</div>}
        </CardContent>
      </Card>
    </section>
  );
}
