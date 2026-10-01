"use client";

import { useEffect, useRef, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { confirmAssignmentPlan, loadAssignmentPlan, requestAssignmentPreview, type AssignmentPreview, type AssignmentReceipt, type Choice, type PreviewReady } from '@/lib/methodologistWorkbench';

const EXAMPLE = 'Назначь курс "Название курса" отделу "Название отдела" до 31.12.2026';
const TIMEZONES = ['Asia/Almaty', 'Asia/Aqtau', 'Asia/Atyrau', 'Asia/Oral', 'Asia/Qostanay', 'Asia/Qyzylorda'];
const formatDue = (value: string, timezone: string) => new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(new Date(value));
const clarificationMessage = (code: string) => ({
  instruction_unsupported: 'Команда не распознана. Используйте точный формат: «Назначь курс "Название курса" отделу "Название отдела" до ДД.ММ.ГГГГ».',
  deadline_invalid: 'Укажите корректную дату в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.',
  deadline_passed: 'Дата назначения уже прошла. Укажите будущую дату.',
  timezone_invalid: 'Выберите корректный часовой пояс IANA, например Asia/Almaty.',
  context_invalid: 'Проверьте команду и явно укажите курс, отдел и дату.',
  resource_not_found: 'Курс или отдел не найден. Проверьте точное название.',
  choose_exact_resources: 'Выберите точный курс и отдел из предложенных вариантов.',
  too_many_matches: 'Найдено слишком много вариантов. Уточните точное название курса или отдела.',
}[code] ?? 'Не удалось однозначно подготовить назначение. Уточните точное название курса, отдела и дату.');

export default function AssignmentWorkbench() {
  const role = useAuthStore((state) => state.user?.role);
  const sessionKey = useAuthStore((state) => `${state.accessToken ?? ''}:${state.user?.user_id ?? ''}`);
  if (process.env.NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED !== 'true') return null;
  if (role !== 'methodologist') return <Card><CardContent className="p-6"><p>Доступ только для методолога.</p></CardContent></Card>;
  return <AssignmentWorkbenchInner key={`${sessionKey}:${role}`} />;
}

function AssignmentWorkbenchInner() {
  const [instruction, setInstruction] = useState(EXAMPLE);
  const [timezone, setTimezone] = useState('Asia/Almaty');
  const [notify, setNotify] = useState(false);
  const [includeDescendants, setIncludeDescendants] = useState(false);
  const [courseId, setCourseId] = useState('');
  const [departmentId, setDepartmentId] = useState('');
  const [preview, setPreview] = useState<AssignmentPreview | null>(null);
  const [receipt, setReceipt] = useState<AssignmentReceipt | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoredPlan, setRestoredPlan] = useState(false);
  const epoch = useRef(0);
  const previewContext = useRef<string | null>(null);

  const contextKey = `${instruction}\u0000${timezone}\u0000${notify}\u0000${includeDescendants}`;
  const visiblePreview = previewContext.current === contextKey ? preview : null;
  const replacePlanUrl = (planId?: string) => {
    if (typeof window === 'undefined') return;
    window.history.replaceState(window.history.state, '', planId ? `${window.location.pathname}?plan=${encodeURIComponent(planId)}` : window.location.pathname);
  };
  const clearContext = (resetChoices = true) => { epoch.current += 1; previewContext.current = null; setPreview(null); setReceipt(null); setError(null); setPending(false); setRestoredPlan(false); replacePlanUrl(); if (resetChoices) { setCourseId(''); setDepartmentId(''); } };
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const planId = new URLSearchParams(window.location.search).get('plan');
    if (!planId) return;
    const current = ++epoch.current;
    const controller = new AbortController();
    setPending(true);
    void loadAssignmentPlan(planId, controller.signal).then((result) => {
      if (current !== epoch.current) return;
      setRestoredPlan(true);
      if (result.state === 'preview_ready') {
        setTimezone(result.timezone_name);
        setNotify(result.notify);
        setIncludeDescendants(result.include_descendants);
        previewContext.current = `${instruction}\u0000${result.timezone_name}\u0000${result.notify}\u0000${result.include_descendants}`;
        setPreview(result);
      } else if (result.state === 'clarification_needed') {
        previewContext.current = null;
        setPreview(result);
      }
      if (result.state === 'succeeded') setReceipt(result);
    }).catch((cause) => {
      if (current === epoch.current && cause instanceof Error && cause.name !== 'CanceledError' && cause.name !== 'AbortError') {
        setError(cause.message);
        replacePlanUrl();
      }
    }).finally(() => { if (current === epoch.current) setPending(false); });
    return () => { controller.abort(); epoch.current += 1; };
    // Authenticated remount (and StrictMode replay) must create a fresh request;
    // cleanup cancels the predecessor, never a ref that suppresses its replacement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const choices = (items: Choice[], value: string, setValue: (value: string) => void, label: string) => items.length > 0 && (
    <label className="block space-y-1"><span className="text-sm font-medium">{label}</span><select className="w-full rounded-md border bg-background px-3 py-2" value={value} onChange={(event) => { setValue(event.target.value); if (preview?.state === 'preview_ready') clearContext(); }}><option value="">Выберите вариант</option>{items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
  );

  const requestPreview = async () => {
    const current = ++epoch.current;
    setPending(true); setError(null); setPreview(null); setReceipt(null);
    try {
      const result = await requestAssignmentPreview({ instruction, timezone_name: timezone, notify, include_descendants: includeDescendants, ...(courseId ? { course_id: courseId } : {}), ...(departmentId ? { department_id: departmentId } : {}) });
      if (current === epoch.current) { previewContext.current = contextKey; setPreview(result); setRestoredPlan(false); if (result.state === 'preview_ready') replacePlanUrl(result.plan_id); else replacePlanUrl(); }
    } catch (cause) { if (current === epoch.current) setError(cause instanceof Error ? cause.message : 'Не удалось построить предварительный просмотр.'); }
    finally { if (current === epoch.current) setPending(false); }
  };
  const confirm = async () => {
    if (!visiblePreview || visiblePreview.state !== 'preview_ready' || pending) return;
    const current = ++epoch.current; setPending(true); setError(null);
    try { const result = await confirmAssignmentPlan(visiblePreview); if (current === epoch.current) { setReceipt(result); previewContext.current = null; setPreview(null); } }
    catch (cause) { if (current === epoch.current) { setPreview(null); setError(cause instanceof Error ? cause.message : 'Подтверждение не выполнено.'); } }
    finally { if (current === epoch.current) setPending(false); }
  };
  return <div className="mx-auto max-w-4xl space-y-6">
    <Card><CardHeader><CardTitle>Назначение курса</CardTitle></CardHeader><CardContent className="space-y-4">
      <label className="block space-y-1"><span className="text-sm font-medium">Команда</span><textarea className="min-h-28 w-full rounded-md border bg-background px-3 py-2" value={instruction} onChange={(event) => { setInstruction(event.target.value); clearContext(); }} aria-label="Команда назначения" /><span className="text-xs text-muted-foreground">Пример: {EXAMPLE}</span></label>
      {restoredPlan && <div className="rounded-md border border-blue-300 p-3 text-sm" role="status">Восстановлен серверный план. Исходная команда не сохраняется и не восстанавливается; измените контекст или начните новую команду.</div>}
      <div className="grid gap-4 sm:grid-cols-2"><label className="block space-y-1"><span className="text-sm font-medium">Часовой пояс</span><select className="w-full rounded-md border bg-background px-3 py-2" value={timezone} onChange={(event) => { setTimezone(event.target.value); clearContext(); }}>{(TIMEZONES.includes(timezone) ? TIMEZONES : [timezone, ...TIMEZONES]).map((item) => <option key={item}>{item}</option>)}</select></label><label className="flex items-center gap-2 pt-6"><input type="checkbox" checked={notify} onChange={(event) => { setNotify(event.target.checked); clearContext(); }} /> Уведомить получателей</label></div>
      <label className="flex items-center gap-2"><input type="checkbox" checked={includeDescendants} onChange={(event) => { setIncludeDescendants(event.target.checked); clearContext(); }} /> Включить дочерние отделы</label>
      {visiblePreview?.state === 'clarification_needed' && <div className="space-y-3 rounded-md border border-amber-300 p-4"><p>{clarificationMessage(visiblePreview.code)}</p>{choices(visiblePreview.course_choices, courseId, setCourseId, 'Курс')}{choices(visiblePreview.department_choices, departmentId, setDepartmentId, 'Отдел')}</div>}
      <Button type="button" onClick={() => void requestPreview()} disabled={pending || restoredPlan || instruction.trim().length < 1 || instruction.length > 4000}>{pending ? 'Обработка…' : 'Показать предварительный просмотр'}</Button>
      {(restoredPlan || receipt) && <Button type="button" variant="outline" disabled={pending} onClick={() => { setInstruction(EXAMPLE); setTimezone('Asia/Almaty'); setNotify(false); setIncludeDescendants(false); clearContext(); }}>Новая команда</Button>}
    </CardContent></Card>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {visiblePreview?.state === 'preview_ready' && <PreviewCard preview={visiblePreview} pending={pending} onConfirm={() => void confirm()} />}
    {receipt && <Card><CardHeader><CardTitle>Назначение принято</CardTitle></CardHeader><CardContent><p>Создано: {receipt.created.length}; пропущено: {receipt.skipped.length}.</p><p>Уведомления: {receipt.notification_state === 'queued' ? 'поставлены в очередь (не доставлены)' : 'не запрашивались'}.</p></CardContent></Card>}
  </div>;
}

function PreviewCard({ preview, pending, onConfirm }: { preview: PreviewReady; pending: boolean; onConfirm: () => void }) {
  return <Card className="border-amber-300"><CardHeader><CardTitle>Проверьте назначение</CardTitle></CardHeader><CardContent className="space-y-3"><dl className="grid gap-2 sm:grid-cols-2">{[['Курс', `${preview.course_title} (${preview.course_id})`], ['Релиз', preview.release_id], ['Отдел', `${preview.department_name} (${preview.department_id})`], ['Часовой пояс', preview.timezone_name], ['Срок', formatDue(preview.due_at, preview.timezone_name)], ['Уведомление', preview.notify ? 'да' : 'нет'], ['Область', preview.include_descendants ? 'отдел и дочерние' : 'только отдел']].map(([key, value]) => <div key={key}><dt className="text-xs text-muted-foreground">{key}</dt><dd>{value}</dd></div>)}</dl><p>Получатели: {preview.recipients.length}; новые: {preview.new_count}; пропущены: {preview.skipped_count}</p><ul className="max-h-48 overflow-auto rounded border p-2 text-sm">{preview.recipients.map((recipient) => <li key={recipient.user_id}>{recipient.label}{recipient.already_assigned ? ' — уже назначен' : ''}{recipient.access_warning ? ' — нет подтверждённого доступа к входу; назначение аккаунт не активирует' : ''}</li>)}</ul><Button type="button" onClick={onConfirm} disabled={pending}>{pending ? 'Подтверждение…' : 'Подтвердить назначение'}</Button></CardContent></Card>;
}
