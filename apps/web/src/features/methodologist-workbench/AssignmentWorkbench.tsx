"use client";

import { useEffect, useRef, useState } from 'react';
import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { confirmAssignmentPlan, interpretAssignment, isAssignmentCandidate, loadAssignmentPlan, requestAssignmentPreview, type AssignmentCandidate, type AssignmentPreview, type AssignmentReceipt, type Choice, type PreviewReady } from '@/lib/methodologistWorkbench';

const EXAMPLE = 'Назначь курс "Название курса" отделу "Название отдела" до 31.12.2026';
const TIMEZONES = ['Asia/Almaty', 'Asia/Aqtau', 'Asia/Atyrau', 'Asia/Oral', 'Asia/Qostanay', 'Asia/Qyzylorda'];
const normalizeCandidateTime = (value: string): string => /^\d{2}:\d{2}$/.test(value) ? `${value}:00` : value;
const NATURAL_MESSAGES = {
  ru: { mode: 'Свободное описание', exact: 'Точная команда', description: 'Можно описать одно назначение свободным текстом. Проверьте предложенные поля; интерпретация ничего не назначает.', correction: 'Уточните поручение в новом описании; предыдущий план используется только как контекст.', interpret: 'Разобрать поручение', course: 'Курс', department: 'Отдел', date: 'Дата', time: 'Время', warning: 'Не вводите секреты и персональные данные. Свободный текст не даёт разрешения на назначение.', clarify: 'Уточнить поручение', relative: 'Укажите точную дату и время.', provider: 'Интерпретация временно недоступна. Повторите действие явно.', invalid: 'Не удалось проверить ответ интерпретации. Уточните поручение.', ambiguous: 'Уточните курс, отдел, дату и время.', previous: 'Предыдущий план нельзя уточнить: он истёк или ещё не готов.' },
  kk: { mode: 'Еркін сипаттама', exact: 'Нақты команда', description: 'Бір тағайындауды еркін мәтінмен сипаттауға болады. Ұсынылған өрістерді тексеріңіз; талдау ештеңе тағайындамайды.', correction: 'Тапсырманы жаңа сипаттамамен нақтылаңыз; алдыңғы жоспар тек контекст ретінде қолданылады.', interpret: 'Тапсырманы талдау', course: 'Курс', department: 'Бөлім', date: 'Күн', time: 'Уақыт', warning: 'Құпияларды және жеке деректерді енгізбеңіз. Еркін мәтін тағайындауға рұқсат бермейді.', clarify: 'Тапсырманы нақтылау', relative: 'Нақты күн мен уақытты көрсетіңіз.', provider: 'Талдау уақытша қолжетімсіз. Әрекетті нақты қайталаңыз.', invalid: 'Талдау жауабын тексеру мүмкін болмады. Тапсырманы нақтылаңыз.', ambiguous: 'Курс, бөлім, күн және уақытты нақтылаңыз.', previous: 'Алдыңғы тапсырманы нақтылау мүмкін емес: жоспар мерзімі өткен немесе дайын емес.' },
  en: { mode: 'Free-text description', exact: 'Exact command', description: 'Describe one assignment in free text. Review the proposed fields; interpretation assigns nothing.', correction: 'Write a correction in a new description; the previous plan is used only as context.', interpret: 'Interpret assignment', course: 'Course', department: 'Department', date: 'Date', time: 'Time', warning: 'Do not enter secrets or personal data. Free text does not authorize an assignment.', clarify: 'Clarify assignment', relative: 'Provide an exact date and time.', provider: 'Interpretation is temporarily unavailable. Explicitly try again.', invalid: 'The interpretation response could not be validated. Clarify the assignment.', ambiguous: 'Clarify the course, department, date, and time.', previous: 'The previous plan cannot be clarified because it is expired or not ready.' },
} as const;
const MESSAGES = {
  ru: { title: 'Назначение курса', purpose: 'Составьте команду для предварительной проверки назначения курса отделу. Предварительный просмотр ничего не назначает; действие выполняется только после подтверждения.', command: 'Команда назначения', commandAria: 'Команда назначения', example: `Пример формата (только подсказка): ${EXAMPLE}`, parser: 'Поддерживается только точный русский синтаксис команды; свободный текст и другие языки пока не распознаются.', timezone: 'Часовой пояс', notify: 'Уведомить получателей', descendants: 'Включить дочерние отделы', choose: 'Выберите вариант', preview: 'Показать предварительный просмотр', processing: 'Обработка…', newCommand: 'Новая команда', restored: 'Восстановлен серверный план. Исходная команда не сохраняется и не восстанавливается; измените контекст или начните новую команду.', clarification: 'Не удалось однозначно подготовить назначение.', course: 'Курс', department: 'Отдел', check: 'Проверьте назначение', confirm: 'Подтвердить назначение', confirming: 'Подтверждение…', receipt: 'Назначение принято', created: 'Создано', skipped: 'пропущено', notifications: 'Уведомления', queued: 'поставлены в очередь (не доставлены)', notRequested: 'не запрашивались', recipients: 'Получатели', newCount: 'новые', scope: 'Область', onlyDepartment: 'только отдел', withChildren: 'отдел и дочерние', release: 'Релиз', due: 'Срок', access: 'нет подтверждённого доступа к входу; назначение аккаунт не активирует', already: 'уже назначен', yes: 'да', no: 'нет', accessDenied: 'Доступ только для методолога.', unsupported: 'Команда не распознана. Используйте точный формат: «Назначь курс "Название курса" отделу "Название отдела" до ДД.ММ.ГГГГ».', deadlineInvalid: 'Укажите корректную дату в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.', deadlinePassed: 'Дата назначения уже прошла. Укажите будущую дату.', timezoneInvalid: 'Выберите корректный часовой пояс IANA, например Asia/Almaty.', contextInvalid: 'Проверьте команду и явно укажите курс, отдел и дату.', resourceNotFound: 'Курс или отдел не найден. Проверьте точное название.', chooseExact: 'Выберите точный курс и отдел из предложенных вариантов.', tooMany: 'Найдено слишком много вариантов. Уточните точное название курса или отдела.', newPlan: 'Не удалось однозначно подготовить назначение. Уточните точное название курса, отдела и дату.' },
  kk: { title: 'Курсты тағайындау', purpose: 'Курсты бөлімге тағайындауды алдын ала тексеру үшін команда құрастырыңыз. Алдын ала қарау ештеңе тағайындамайды; әрекет тек растаудан кейін орындалады.', command: 'Тағайындау командасы', commandAria: 'Тағайындау командасы', example: `Пішім мысалы (тек көмек): ${EXAMPLE}`, parser: 'Тек нақты орысша команда синтаксисіне қолдау бар; еркін мәтін және басқа тілдер әзірге танылмайды.', timezone: 'Уақыт белдеуі', notify: 'Алушыларға хабарлау', descendants: 'Бағынышты бөлімдерді қосу', choose: 'Нұсқаны таңдаңыз', preview: 'Алдын ала қарауды көрсету', processing: 'Өңделуде…', newCommand: 'Жаңа команда', restored: 'Серверлік жоспар қалпына келтірілді. Бастапқы команда сақталмайды және қалпына келтірілмейді; контексті өзгертіңіз немесе жаңа команда бастаңыз.', clarification: 'Тағайындауды нақты дайындау мүмкін болмады.', course: 'Курс', department: 'Бөлім', check: 'Тағайындауды тексеріңіз', confirm: 'Тағайындауды растау', confirming: 'Расталуда…', receipt: 'Тағайындау қабылданды', created: 'Құрылды', skipped: 'өткізілді', notifications: 'Хабарламалар', queued: 'кезекке қойылды (жеткізілмеді)', notRequested: 'сұралмады', recipients: 'Алушылар', newCount: 'жаңа', scope: 'Ауқым', onlyDepartment: 'тек бөлім', withChildren: 'бөлім және бағыныштылар', release: 'Релиз', due: 'Мерзім', access: 'кіруге расталған рұқсат жоқ; тағайындау аккаунтты белсендірмейді', already: 'тағайындалған', yes: 'иә', no: 'жоқ', accessDenied: 'Бұл бөлімге тек әдіскерлер кіре алады.', unsupported: 'Команда танылмады. Нақты пішімді қолданыңыз: «Назначь курс "Название курса" отделу "Название отдела" до ДД.ММ.ГГГГ».', deadlineInvalid: 'ДД.ММ.ГГГГ немесе ГГГГ-ММ-ДД форматындағы дұрыс күнді көрсетіңіз.', deadlinePassed: 'Тағайындау күні өтіп кетті. Болашақ күнді көрсетіңіз.', timezoneInvalid: 'Asia/Almaty сияқты дұрыс IANA уақыт белдеуін таңдаңыз.', contextInvalid: 'Команданы тексеріп, курс, бөлім және күнді нақты көрсетіңіз.', resourceNotFound: 'Курс немесе бөлім табылмады. Нақты атауын тексеріңіз.', chooseExact: 'Ұсынылған нұсқалардан нақты курс пен бөлімді таңдаңыз.', tooMany: 'Тым көп нұсқа табылды. Курс немесе бөлімнің нақты атауын көрсетіңіз.', newPlan: 'Тағайындауды нақты дайындау мүмкін болмады. Курс, бөлім және күн атауын нақтылаңыз.' },
  en: { title: 'Assign a course', purpose: 'Compose a command for a course-to-department assignment preview. The preview assigns nothing; the action runs only after confirmation.', command: 'Assignment command', commandAria: 'Assignment command', example: `Format example (hint only): ${EXAMPLE}`, parser: 'Only the exact Russian command syntax is supported; free text and other languages are not recognized yet.', timezone: 'Time zone', notify: 'Notify recipients', descendants: 'Include child departments', choose: 'Choose an option', preview: 'Show preview', processing: 'Processing…', newCommand: 'New command', restored: 'A server plan was restored. The original command is not saved or restored; change the context or start a new command.', clarification: 'The assignment could not be prepared unambiguously.', course: 'Course', department: 'Department', check: 'Review assignment', confirm: 'Confirm assignment', confirming: 'Confirming…', receipt: 'Assignment accepted', created: 'Created', skipped: 'skipped', notifications: 'Notifications', queued: 'queued (not delivered)', notRequested: 'not requested', recipients: 'Recipients', newCount: 'new', scope: 'Scope', onlyDepartment: 'department only', withChildren: 'department and children', release: 'Release', due: 'Due date', access: 'no confirmed sign-in access; assignment does not activate the account', already: 'already assigned', yes: 'yes', no: 'no', accessDenied: 'Only methodologists can access this section.', unsupported: 'Command not recognized. Use the exact format: «Назначь курс "Название курса" отделу "Название отдела" до ДД.ММ.ГГГГ».', deadlineInvalid: 'Enter a valid date as ДД.ММ.ГГГГ or ГГГГ-ММ-ДД.', deadlinePassed: 'The assignment date has passed. Enter a future date.', timezoneInvalid: 'Choose a valid IANA time zone, for example Asia/Almaty.', contextInvalid: 'Check the command and specify the course, department, and date.', resourceNotFound: 'Course or department was not found. Check the exact name.', chooseExact: 'Choose the exact course and department from the options.', tooMany: 'Too many matches were found. Clarify the exact course or department name.', newPlan: 'The assignment could not be prepared unambiguously. Clarify the course, department, and date.' },
} as const;
type WorkbenchMessages = typeof MESSAGES[keyof typeof MESSAGES];
type NaturalMessages = typeof NATURAL_MESSAGES[keyof typeof NATURAL_MESSAGES];
const WORKSPACE_TITLES = { ru: 'Рабочее место методиста', kk: 'Әдіскердің жұмыс орны', en: 'Methodologist workbench' } as const;
const formatDue = (value: string, timezone: string, lang: keyof typeof MESSAGES) => new Intl.DateTimeFormat({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[lang], { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(new Date(value));
const clarificationMessage = (code: string, ui: WorkbenchMessages, naturalUi: NaturalMessages) => ({ instruction_unsupported: ui.unsupported, deadline_invalid: ui.deadlineInvalid, deadline_passed: ui.deadlinePassed, timezone_invalid: ui.timezoneInvalid, context_invalid: ui.contextInvalid, resource_not_found: ui.resourceNotFound, choose_exact_resources: ui.chooseExact, too_many_matches: ui.tooMany, intent_relative_deadline: naturalUi.relative, intent_provider_unavailable: naturalUi.provider, intent_invalid_response: naturalUi.invalid, intent_clarification: naturalUi.ambiguous, previous_plan_not_ready: naturalUi.previous }[code] ?? ui.newPlan);

export default function AssignmentWorkbench() {
  const role = useAuthStore((state) => state.user?.role);
  const lang = useLanguageStore((state) => state.lang);
  const accessUi = MESSAGES[lang] ?? MESSAGES.ru;
  const sessionKey = useAuthStore((state) => `${state.accessToken ?? ''}:${state.user?.user_id ?? ''}`);
  if (process.env.NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED !== 'true') return null;
  if (role !== 'methodologist') return <Card><CardContent className="p-6"><p>{accessUi.accessDenied}</p></CardContent></Card>;
  return <AssignmentWorkbenchInner key={`${sessionKey}:${role}`} />;
}

function AssignmentWorkbenchInner() {
  const lang = useLanguageStore((state) => state.lang);
  const ui = MESSAGES[lang] ?? MESSAGES.ru;
  const naturalUi = NATURAL_MESSAGES[lang] ?? NATURAL_MESSAGES.ru;
  const [instruction, setInstruction] = useState('');
  const [naturalMode, setNaturalMode] = useState(false);
  const [candidate, setCandidate] = useState<AssignmentCandidate | null>(null);
  const [previousPlanId, setPreviousPlanId] = useState<string | undefined>();
  const [correctionContext, setCorrectionContext] = useState(false);
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
  const interpretationController = useRef<AbortController | null>(null);

  const contextKey = `${naturalMode}\u0000${instruction}\u0000${timezone}\u0000${notify}\u0000${includeDescendants}\u0000${candidate ? JSON.stringify(candidate) : ''}`;
  const visiblePreview = previewContext.current === contextKey ? preview : null;
  const replacePlanUrl = (planId?: string) => {
    if (typeof window === 'undefined') return;
    window.history.replaceState(window.history.state, '', planId ? `${window.location.pathname}?plan=${encodeURIComponent(planId)}` : window.location.pathname);
  };
  const clearContext = (resetChoices = true) => { interpretationController.current?.abort(); interpretationController.current = null; epoch.current += 1; previewContext.current = null; setPreview(null); setReceipt(null); setError(null); setPending(false); setRestoredPlan(false); replacePlanUrl(); if (resetChoices) { setCourseId(''); setDepartmentId(''); } };
  useEffect(() => () => { interpretationController.current?.abort(); }, []);
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
        previewContext.current = `${naturalMode}\u0000${instruction}\u0000${result.timezone_name}\u0000${result.notify}\u0000${result.include_descendants}\u0000`;
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
    <label className="block space-y-1"><span className="text-sm font-medium">{label}</span><select className="w-full rounded-md border bg-background px-3 py-2" value={value} onChange={(event) => { setValue(event.target.value); if (preview?.state === 'preview_ready') clearContext(); }}><option value="">{ui.choose}</option>{items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
  );

  const requestPreview = async () => {
    const current = ++epoch.current;
    setPending(true); setError(null); setPreview(null); setReceipt(null);
    try {
      const result = await requestAssignmentPreview({ instruction, timezone_name: timezone, notify: candidate?.notify ?? notify, include_descendants: candidate?.include_descendants ?? includeDescendants, ...(courseId ? { course_id: courseId } : {}), ...(departmentId ? { department_id: departmentId } : {}), ...(candidate ? { candidate } : {}) });
      if (current === epoch.current) { previewContext.current = contextKey; setPreview(result); setRestoredPlan(false); if (result.state === 'preview_ready') replacePlanUrl(result.plan_id); else replacePlanUrl(); }
    } catch (cause) { if (current === epoch.current) setError(cause instanceof Error ? cause.message : ui.newPlan); }
    finally { if (current === epoch.current) setPending(false); }
  };
  const interpret = async (requestedPreviousPlanId?: string) => {
    const planForRequest = requestedPreviousPlanId ?? previousPlanId;
    clearContext();
    const current = ++epoch.current;
    const controller = new AbortController();
    interpretationController.current = controller;
    setCandidate(null);
    setPending(true); setError(null); setPreview(null); setReceipt(null);
    try {
      const result = await interpretAssignment(instruction, timezone, notify, includeDescendants, planForRequest, controller.signal);
      if (current !== epoch.current) return;
      setRestoredPlan(false);
      if (result.state === 'interpreted') { setPreviousPlanId(undefined); setCorrectionContext(false); setCandidate(result.candidate); setNotify(result.candidate.notify); setIncludeDescendants(result.candidate.include_descendants); previewContext.current = null; }
      else { setCandidate(null); previewContext.current = `${naturalMode}\u0000${instruction}\u0000${timezone}\u0000${notify}\u0000${includeDescendants}\u0000`; setPreview(result); }
    } catch (cause) { if (current === epoch.current && cause instanceof Error && cause.name !== 'AbortError' && cause.name !== 'CanceledError') { setCandidate(null); setError(cause.message); } }
    finally { if (current === epoch.current) setPending(false); }
  };
  const confirm = async () => {
    if (!visiblePreview || visiblePreview.state !== 'preview_ready' || pending) return;
    const current = ++epoch.current; setPending(true); setError(null);
    try { const result = await confirmAssignmentPlan(visiblePreview); if (current === epoch.current) { setReceipt(result); previewContext.current = null; setPreview(null); } }
    catch (cause) { if (current === epoch.current) { setPreview(null); setError(cause instanceof Error ? cause.message : ui.confirm); } }
    finally { if (current === epoch.current) setPending(false); }
  };
  return <div className="mx-auto max-w-4xl space-y-6">
    <Card><CardHeader><h1 className="text-2xl font-semibold leading-none tracking-tight">{WORKSPACE_TITLES[lang]}</h1><CardTitle>{ui.title}</CardTitle><p className="text-sm text-muted-foreground">{ui.purpose}</p></CardHeader><CardContent className="space-y-4">
      <div className="flex gap-2"><Button type="button" variant={naturalMode ? 'default' : 'outline'} onClick={() => { setNaturalMode(true); setPreviousPlanId(undefined); setCorrectionContext(false); setCandidate(null); clearContext(); }}>{naturalUi.mode}</Button><Button type="button" variant={!naturalMode ? 'default' : 'outline'} onClick={() => { setNaturalMode(false); setPreviousPlanId(undefined); setCorrectionContext(false); setCandidate(null); clearContext(); }}>{naturalUi.exact}</Button></div>
      {correctionContext && <div className="rounded-md border border-blue-300 p-3 text-sm" role="status">{naturalUi.correction}</div>}
      <label className="block space-y-1"><span className="text-sm font-medium">{ui.command}</span><textarea className="min-h-28 w-full rounded-md border bg-background px-3 py-2" value={instruction} placeholder={EXAMPLE} onChange={(event) => { setInstruction(event.target.value); setCandidate(null); clearContext(); }} aria-label={ui.commandAria} aria-describedby="assignment-command-example assignment-command-parser" /><span id="assignment-command-example" className="text-xs text-muted-foreground">{naturalMode ? naturalUi.description : ui.example}</span><span id="assignment-command-parser" className="block text-xs text-muted-foreground">{naturalMode ? naturalUi.warning : ui.parser}</span></label>
      {restoredPlan && <div className="rounded-md border border-blue-300 p-3 text-sm" role="status">{ui.restored}</div>}
      <div className="grid gap-4 sm:grid-cols-2"><label className="block space-y-1"><span className="text-sm font-medium">{ui.timezone}</span><select className="w-full rounded-md border bg-background px-3 py-2" value={timezone} aria-label={ui.timezone} onChange={(event) => { setTimezone(event.target.value); clearContext(); }}>{(TIMEZONES.includes(timezone) ? TIMEZONES : [timezone, ...TIMEZONES]).map((item) => <option key={item}>{item}</option>)}</select></label>{(!naturalMode || !candidate) && <label className="flex items-center gap-2 pt-6"><input type="checkbox" checked={notify} onChange={(event) => { setNotify(event.target.checked); clearContext(); }} /> {ui.notify}</label>}</div>
      {(!naturalMode || !candidate) && <label className="flex items-center gap-2"><input type="checkbox" checked={includeDescendants} onChange={(event) => { setIncludeDescendants(event.target.checked); clearContext(); }} /> {ui.descendants}</label>}
      {visiblePreview?.state === 'clarification_needed' && <div className="space-y-3 rounded-md border border-amber-300 p-4" role="status"><p>{clarificationMessage(visiblePreview.code, ui, naturalUi)}</p>{choices(visiblePreview.course_choices, courseId, setCourseId, ui.course)}{choices(visiblePreview.department_choices, departmentId, setDepartmentId, ui.department)}</div>}
      {naturalMode && candidate && <div className="space-y-3 rounded-md border p-4"><label className="block space-y-1"><span className="text-sm font-medium">{naturalUi.course}</span><input className="w-full rounded-md border bg-background px-3 py-2" value={candidate.course_query} onChange={(event) => { setCandidate({ ...candidate, course_query: event.target.value }); clearContext(); }} /></label><label className="block space-y-1"><span className="text-sm font-medium">{naturalUi.department}</span><input className="w-full rounded-md border bg-background px-3 py-2" value={candidate.department_query} onChange={(event) => { setCandidate({ ...candidate, department_query: event.target.value }); clearContext(); }} /></label><div className="grid gap-3 sm:grid-cols-2"><label className="block space-y-1"><span className="text-sm font-medium">{naturalUi.date}</span><input type="date" className="w-full rounded-md border bg-background px-3 py-2" value={candidate.due_date} onChange={(event) => { setCandidate({ ...candidate, due_date: event.target.value }); clearContext(); }} /></label><label className="block space-y-1"><span className="text-sm font-medium">{naturalUi.time}</span><input type="time" step="1" className="w-full rounded-md border bg-background px-3 py-2" value={candidate.due_time} onChange={(event) => { setCandidate({ ...candidate, due_time: normalizeCandidateTime(event.target.value) }); clearContext(); }} /></label></div><label className="flex items-center gap-2"><input type="checkbox" checked={candidate.notify} onChange={(event) => { const value = event.target.checked; setCandidate({ ...candidate, notify: value }); setNotify(value); clearContext(); }} />{ui.notify}</label><label className="flex items-center gap-2"><input type="checkbox" checked={candidate.include_descendants} onChange={(event) => { const value = event.target.checked; setCandidate({ ...candidate, include_descendants: value }); setIncludeDescendants(value); clearContext(); }} />{ui.descendants}</label></div>}
      {naturalMode && <Button type="button" onClick={() => void interpret()} disabled={pending || restoredPlan || instruction.trim().length < 1 || instruction.length > 4000}>{pending ? ui.processing : naturalUi.interpret}</Button>}
      <Button type="button" onClick={() => void requestPreview()} disabled={pending || restoredPlan || instruction.trim().length < 1 || instruction.length > 4000 || (naturalMode && (!candidate || !isAssignmentCandidate(candidate)))}>{pending ? ui.processing : ui.preview}</Button>
      {naturalMode && visiblePreview?.state === 'preview_ready' && <Button type="button" variant="outline" onClick={() => { setPreviousPlanId(visiblePreview.plan_id); setCorrectionContext(true); setInstruction(''); setCandidate(null); clearContext(); }} disabled={pending}>{naturalUi.clarify}</Button>}
      {(restoredPlan || receipt) && <Button type="button" variant="outline" disabled={pending} onClick={() => { setInstruction(''); setTimezone('Asia/Almaty'); setNotify(false); setIncludeDescendants(false); setCandidate(null); setPreviousPlanId(undefined); setCorrectionContext(false); clearContext(); }}>{ui.newCommand}</Button>}
    </CardContent></Card>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {visiblePreview?.state === 'preview_ready' && <PreviewCard preview={visiblePreview} pending={pending} onConfirm={() => void confirm()} ui={ui} lang={lang} />}
    {receipt && <Card><CardHeader><CardTitle>{ui.receipt}</CardTitle></CardHeader><CardContent><p>{ui.created}: {receipt.created.length}; {ui.skipped}: {receipt.skipped.length}.</p><p>{ui.notifications}: {receipt.notification_state === 'queued' ? ui.queued : ui.notRequested}.</p></CardContent></Card>}
  </div>;
}

function PreviewCard({ preview, pending, onConfirm, ui, lang }: { preview: PreviewReady; pending: boolean; onConfirm: () => void; ui: WorkbenchMessages; lang: keyof typeof MESSAGES }) {
  return <Card className="border-amber-300"><CardHeader><CardTitle>{ui.check}</CardTitle><p className="text-sm text-muted-foreground">{ui.purpose}</p></CardHeader><CardContent className="space-y-3"><dl className="grid gap-2 sm:grid-cols-2">{[[ui.course, `${preview.course_title} (${preview.course_id})`], [ui.release, preview.release_id], [ui.department, `${preview.department_name} (${preview.department_id})`], [ui.timezone, preview.timezone_name], [ui.due, formatDue(preview.due_at, preview.timezone_name, lang)], [ui.notify, preview.notify ? ui.yes : ui.no], [ui.scope, preview.include_descendants ? ui.withChildren : ui.onlyDepartment]].map(([key, value]) => <div key={key}><dt className="text-xs text-muted-foreground">{key}</dt><dd>{value}</dd></div>)}</dl><p>{ui.recipients}: {preview.recipients.length}; {ui.newCount}: {preview.new_count}; {ui.skipped}: {preview.skipped_count}</p><ul className="max-h-48 overflow-auto rounded border p-2 text-sm">{preview.recipients.map((recipient) => <li key={recipient.user_id}>{recipient.label}{recipient.already_assigned ? ` — ${ui.already}` : ''}{recipient.access_warning ? ` — ${ui.access}` : ''}</li>)}</ul><Button type="button" onClick={onConfirm} disabled={pending}>{pending ? ui.confirming : ui.confirm}</Button></CardContent></Card>;
}
