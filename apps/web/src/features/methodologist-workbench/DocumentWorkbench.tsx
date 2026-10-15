"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { useLanguageStore } from '@/store/languageStore';
import { Button, Card, CardContent, CardHeader, CardTitle, Modal } from '@/components/ui';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';
import type { DocumentCatalogItem, DocumentCatalogResponse } from '@/lib/documentCatalog';
import {
  confirmDocumentPlan, interpretDocument, loadDocumentPlan, previewDocumentPlan,
  type AIGenerateRequest, type DocumentCandidate, type DocumentPlan, type DocumentPreview,
} from '@/lib/documentWorkbench';
import {
  createDocumentDialogue, downloadDocumentContentSource, getDocumentContentSourceExcerpt,
  getDocumentDialogue, listDocumentDialogues, messageDocumentContentDialogue, messageDocumentDialogue,
  previewDocumentDialogue, saveDocumentDialogue,
  type DocumentContentCitation, type DocumentDialogueDraft, type DocumentDialogueTask,
} from '@/lib/documentDialogue';

const enabled = () => process.env.NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED === 'true';
const initialCandidate: DocumentCandidate = {
  target_audience: '', course_intent: '', course_format: 'automatic', language: 'ru', source_strategy: 'single_topic', combination_goal: '',
};

type DocumentLocale = 'ru' | 'kk' | 'en';
const DOCUMENT_COPY = {
  ru: { title: 'Документ → черновик курса', description: 'Выберите до пяти проверенных источников, проверьте параметры и подтвердите один неизменяемый план.', upload: 'Загрузить документ', uploading: 'Загрузка документа…', indexing: 'Индексация документа…', catalogError: 'Не удалось загрузить каталог документов.', uploadError: 'Не удалось загрузить документ.', indexingError: 'Индексация документа завершилась с ошибкой.', indexingTimeout: 'Индексация не завершилась в допустимое время.', sources: 'Источники', empty: 'Нет готовых документов.', instruction: 'Инструкция', instructionHelp: 'Инструкция сохраняется в плане как исходный след. Для генерации обязательно укажите редактируемую цель курса ниже; интерпретация инструкции необязательна.', audience: 'Аудитория', goal: 'Цель курса', language: 'Язык', format: 'Формат', languages: { ru: 'Русский', kk: 'Қазақша', en: 'English' }, formats: { automatic: 'Автоматический', brief: 'Краткий', standard: 'Стандартный', detailed: 'Подробный' }, combine: 'Объединить источники с общей целью', combinationPlaceholder: 'Общая учебная цель (не менее 20 символов)', confirmLanguage: 'Я подтверждаю язык будущего курса', reuse: 'Причина повторного использования источника', reuseOptions: { '': 'Не указана', different_audience: 'Другая аудитория', different_language: 'Другой язык', different_depth: 'Другая глубина', updated_revision: 'Обновлённая версия', recurring_training: 'Повторное обучение', other: 'Другое' }, interpret: 'Интерпретировать', prepare: 'Подготовить план', confirm: 'Подтвердить и запустить', previewError: 'Не удалось подготовить предварительный план.', restoreError: 'Не удалось восстановить план документа.', confirmError: 'Не удалось подтвердить план.', stalePlan: 'План устарел или уже подтверждён. Обновите его.', clarify: 'Уточните описание документа и попробуйте снова.', interpretationError: 'Интерпретация временно недоступна.', previewReady: 'План готов · ревизия', audienceMissing: 'не указана', combinationNone: 'нет', reuseMissing: 'не подтверждено', sourcesList: 'Источники:', validUntil: 'Действителен до:', fingerprint: 'Отпечаток:', task: 'Задача:', stage: 'Этап:', progress: 'прогресс', noStage: 'не указан', openCourse: 'Открыть курс', openGeneration: 'Открыть генерацию', indexStatus: { ready: 'готов', partial: 'частично' }, dialogue: 'Подготовка курса', recentTasks: 'Недавние подготовки', startDialogue: 'Начать сохранённую подготовку', saveDraft: 'Сохранить параметры', sendMessage: 'Отправить сообщение', messagePlaceholder: 'Обсудите параметр курса', reloadTask: 'Обновить сохранённую задачу', sourceStale: 'Источник изменился. Начните новую подготовку с текущими документами.', taskError: 'Не удалось загрузить или сохранить подготовку.', saved: 'Сохранено', pendingRequest: 'Запрос ещё обрабатывается. Обновите задачу, чтобы получить статус.', interruptedRequest: 'Предыдущий запрос прерван. Обновите задачу перед продолжением.', exchanges: 'Диалог', noMessages: 'Сообщений пока нет.', moreTasks: 'Показать ещё' },
  kk: { title: 'Құжат → курс жобасы', description: 'Беске дейін тексерілген дереккөзді таңдап, параметрлерді тексеріп, өзгермейтін жоспарды растаңыз.', upload: 'Құжат жүктеу', uploading: 'Құжат жүктелуде…', indexing: 'Құжат индекстелуде…', catalogError: 'Құжаттар каталогын жүктеу мүмкін болмады.', uploadError: 'Құжатты жүктеу мүмкін болмады.', indexingError: 'Құжатты индекстеу қатемен аяқталды.', indexingTimeout: 'Индекстеу рұқсат етілген уақытта аяқталмады.', sources: 'Дереккөздер', empty: 'Дайын құжаттар жоқ.', instruction: 'Нұсқаулық', instructionHelp: 'Нұсқаулық жоспарға бастапқы із ретінде сақталады. Генерация үшін төменде өзгертілетін курс мақсатын көрсетіңіз; нұсқаулықты талдау міндетті емес.', audience: 'Аудитория', goal: 'Курс мақсаты', language: 'Тіл', format: 'Пішім', languages: { ru: 'Орысша', kk: 'Қазақша', en: 'Ағылшынша' }, formats: { automatic: 'Автоматты', brief: 'Қысқа', standard: 'Стандартты', detailed: 'Толық' }, combine: 'Дереккөздерді ортақ мақсатпен біріктіру', combinationPlaceholder: 'Ортақ оқу мақсаты (кемінде 20 таңба)', confirmLanguage: 'Болашақ курс тілін растаймын', reuse: 'Дереккөзді қайта пайдалану себебі', reuseOptions: { '': 'Көрсетілмеген', different_audience: 'Басқа аудитория', different_language: 'Басқа тіл', different_depth: 'Басқа тереңдік', updated_revision: 'Жаңартылған нұсқа', recurring_training: 'Қайта оқыту', other: 'Басқа' }, interpret: 'Талдау', prepare: 'Жоспар дайындау', confirm: 'Растау және іске қосу', previewError: 'Алдын ала жоспарды дайындау мүмкін болмады.', restoreError: 'Құжат жоспарын қалпына келтіру мүмкін болмады.', confirmError: 'Жоспарды растау мүмкін болмады.', stalePlan: 'Жоспар ескірген немесе расталған. Жаңартыңыз.', clarify: 'Құжат сипаттамасын нақтылап, қайталап көріңіз.', interpretationError: 'Талдау уақытша қолжетімсіз.', previewReady: 'Жоспар дайын · нұсқа', audienceMissing: 'көрсетілмеген', combinationNone: 'жоқ', reuseMissing: 'расталмаған', sourcesList: 'Дереккөздер:', validUntil: 'Жарамды мерзімі:', fingerprint: 'Бақылау ізі:', task: 'Тапсырма:', stage: 'Кезең:', progress: 'ілгерілеу', noStage: 'көрсетілмеген', openCourse: 'Курсты ашу', openGeneration: 'Генерацияны ашу', indexStatus: { ready: 'дайын', partial: 'ішінара' }, dialogue: 'Курсты дайындау', recentTasks: 'Соңғы дайындықтар', startDialogue: 'Сақталған дайындықты бастау', saveDraft: 'Параметрлерді сақтау', sendMessage: 'Хабарлама жіберу', messagePlaceholder: 'Курс параметрін талқылаңыз', reloadTask: 'Сақталған тапсырманы жаңарту', sourceStale: 'Дереккөз өзгерді. Қазіргі құжаттармен жаңа дайындықты бастаңыз.', taskError: 'Дайындықты жүктеу немесе сақтау мүмкін болмады.', saved: 'Сақталды', pendingRequest: 'Сұрау әлі өңделуде. Күйін алу үшін тапсырманы жаңартыңыз.', interruptedRequest: 'Алдыңғы сұрау үзілді. Жалғастырмас бұрын жаңартыңыз.', exchanges: 'Диалог', noMessages: 'Әзірше хабарлама жоқ.', moreTasks: 'Тағы көрсету' },
  en: { title: 'Document → course draft', description: 'Choose up to five verified sources, review the parameters, and confirm one immutable plan.', upload: 'Upload document', uploading: 'Uploading document…', indexing: 'Indexing document…', catalogError: 'Could not load the document catalog.', uploadError: 'Could not upload the document.', indexingError: 'Document indexing failed.', indexingTimeout: 'Indexing did not finish within the allowed time.', sources: 'Sources', empty: 'No ready documents.', instruction: 'Instruction', instructionHelp: 'The instruction is saved in the plan as the original trace. For generation, provide an editable course goal below; interpreting the instruction is optional.', audience: 'Audience', goal: 'Course goal', language: 'Language', format: 'Format', languages: { ru: 'Russian', kk: 'Kazakh', en: 'English' }, formats: { automatic: 'Automatic', brief: 'Brief', standard: 'Standard', detailed: 'Detailed' }, combine: 'Combine sources with a shared goal', combinationPlaceholder: 'Shared learning goal (at least 20 characters)', confirmLanguage: 'I confirm the future course language', reuse: 'Reason for reusing the source', reuseOptions: { '': 'Not specified', different_audience: 'Different audience', different_language: 'Different language', different_depth: 'Different depth', updated_revision: 'Updated revision', recurring_training: 'Recurring training', other: 'Other' }, interpret: 'Interpret', prepare: 'Prepare plan', confirm: 'Confirm and launch', previewError: 'Could not prepare the preview plan.', restoreError: 'Could not restore the document plan.', confirmError: 'Could not confirm the plan.', stalePlan: 'The plan is stale or already confirmed. Refresh it.', clarify: 'Clarify the document description and try again.', interpretationError: 'Interpretation is temporarily unavailable.', previewReady: 'Plan ready · revision', audienceMissing: 'not specified', combinationNone: 'none', reuseMissing: 'not confirmed', sourcesList: 'Sources:', validUntil: 'Valid until:', fingerprint: 'Fingerprint:', task: 'Task:', stage: 'Stage:', progress: 'progress', noStage: 'not specified', openCourse: 'Open course', openGeneration: 'Open generation', indexStatus: { ready: 'ready', partial: 'partial' }, dialogue: 'Preparation dialogue', recentTasks: 'Recent preparations', startDialogue: 'Start saved preparation', saveDraft: 'Save parameters', sendMessage: 'Send message', messagePlaceholder: 'Discuss a course parameter', reloadTask: 'Reload saved task', sourceStale: 'A source changed. Start a new preparation with the current documents.', taskError: 'Could not load or save the preparation.', saved: 'Saved', pendingRequest: 'A request is still processing. Reload to recover its status.', interruptedRequest: 'The previous request was interrupted. Reload before continuing.', exchanges: 'Conversation', noMessages: 'No messages yet.', moreTasks: 'Show more' },
} as const;
const localeOf = (lang: string): DocumentLocale => lang === 'kk' || lang === 'en' ? lang : 'ru';
const stableJson = (value: unknown): string => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right))) : item);
const RECOVERY_COPY = {
  ru: { missing: 'Задача не найдена. Можно явно начать новую подготовку.', unknownPlan: 'Результат плана пока не подтверждён. Сначала восстановите его или начните новую подготовку.', confirmUnknown: 'Подтверждение могло завершиться. Восстановите план, чтобы проверить результат.', recoverPlan: 'Восстановить план', newTask: 'Начать новую подготовку', interruptedRequest: 'Предыдущий запрос прерван. После обновления можно явно отправить новое сообщение.' },
  kk: { missing: 'Тапсырма табылмады. Жаңа дайындықты бастауға болады.', unknownPlan: 'Жоспар нәтижесі әлі расталмады. Алдымен қалпына келтіріңіз немесе жаңа дайындықты бастаңыз.', confirmUnknown: 'Растау аяқталған болуы мүмкін. Нәтижені тексеру үшін жоспарды қалпына келтіріңіз.', recoverPlan: 'Жоспарды қалпына келтіру', newTask: 'Жаңа дайындықты бастау', interruptedRequest: 'Алдыңғы сұрау үзілді. Жаңартқаннан кейін жаңа хабарламаны өзіңіз жібере аласыз.' },
  en: { missing: 'The task was not found. You can explicitly start a new preparation.', unknownPlan: 'The plan outcome is not confirmed. Recover it first or start a new preparation.', confirmUnknown: 'Confirmation may have completed. Recover the plan to check its result.', recoverPlan: 'Recover plan', newTask: 'Start new preparation', interruptedRequest: 'The previous request was interrupted. After reload, you can explicitly send a new message.' },
} as const;
const CONTENT_COPY = {
  ru: {
    questionTitle: 'Диалог с документами', startQuestionTask: 'Начать диалог', taskHint: 'Выберите от 1 до 5 документов и начните диалог. Поля брифа курса для вопросов не нужны; генерация курса по-прежнему требует отдельной проверки и подтверждения плана.',
    mode: 'Режим диалога', questionMode: 'Вопрос о содержимом документов', preparationMode: 'Подготовка курса',
    questionPlaceholder: 'Задайте вопрос по выбранным документам', preparationPlaceholder: 'Обсудите параметр курса',
    askQuestion: 'Задать вопрос', sendPreparation: 'Отправить сообщение', questionRecovery: 'Результат вопроса не подтверждён. Обновите задачу, прежде чем продолжать; запрос автоматически не повторяется.',
    planExists: 'В этой задаче уже есть план. Для новых вопросов начните новую задачу, чтобы не менять неизменяемый план.',
    supported: 'Подтверждено источниками', not_found: 'В проверенных фрагментах ответ не найден', conflict: 'В источниках есть противоречие',
    openSource: 'Открыть цитату источника', sourceTitle: 'Фрагмент источника', sourceQuote: 'Цитата из ответа', sourceExcerpt: 'Фрагмент документа',
    sourceLoading: 'Загрузка фрагмента…', downloadSource: 'Скачать исходный документ', downloadLoading: 'Подготовка скачивания…', closeSource: 'Закрыть',
    sourceUnavailable: 'Источник изменился или недоступен; цитату открыть нельзя.', sourceError: 'Не удалось открыть фрагмент источника.', downloadError: 'Не удалось скачать исходный документ.',
  },
  kk: {
    questionTitle: 'Құжаттармен диалог', startQuestionTask: 'Диалогты бастау', taskHint: '1–5 құжатты таңдап, диалогты бастаңыз. Сұрақтар үшін курс брифінің өрістері қажет емес; курсты генерациялау үшін жоспарды бөлек қарап, растау керек.',
    mode: 'Диалог режимі', questionMode: 'Құжат мазмұны туралы сұрақ', preparationMode: 'Курсты дайындау',
    questionPlaceholder: 'Таңдалған құжаттар бойынша сұрақ қойыңыз', preparationPlaceholder: 'Курс параметрін талқылаңыз',
    askQuestion: 'Сұрақ қою', sendPreparation: 'Хабарлама жіберу', questionRecovery: 'Сұрақ нәтижесі расталмады. Жалғастырмас бұрын тапсырманы жаңартыңыз; сұрау автоматты түрде қайталанбайды.',
    planExists: 'Бұл тапсырмада жоспар бар. Өзгермейтін жоспарды өзгертпеу үшін жаңа сұрақтарға жаңа тапсырма бастаңыз.',
    supported: 'Дереккөздер растайды', not_found: 'Тексерілген үзінділерден жауап табылмады', conflict: 'Дереккөздерде қайшылық бар',
    openSource: 'Дереккөз дәйексөзін ашу', sourceTitle: 'Дереккөз үзіндісі', sourceQuote: 'Жауаптағы дәйексөз', sourceExcerpt: 'Құжат үзіндісі',
    sourceLoading: 'Үзінді жүктелуде…', downloadSource: 'Бастапқы құжатты жүктеу', downloadLoading: 'Жүктеу дайындалуда…', closeSource: 'Жабу',
    sourceUnavailable: 'Дереккөз өзгерген немесе қолжетімсіз; дәйексөзді ашу мүмкін емес.', sourceError: 'Дереккөз үзіндісін ашу мүмкін болмады.', downloadError: 'Бастапқы құжатты жүктеу мүмкін болмады.',
  },
  en: {
    questionTitle: 'Dialogue with documents', startQuestionTask: 'Start dialogue', taskHint: 'Select 1–5 documents to start a dialogue. Course brief fields are not needed for questions; generating a course still requires a separate plan review and confirmation.',
    mode: 'Dialogue mode', questionMode: 'Question about document content', preparationMode: 'Course preparation',
    questionPlaceholder: 'Ask about the selected documents', preparationPlaceholder: 'Discuss a course parameter',
    askQuestion: 'Ask question', sendPreparation: 'Send preparation message', questionRecovery: 'The question outcome is not confirmed. Reload the task before continuing; the request will not be retried automatically.',
    planExists: 'This task already has a plan. Start a new task for more questions so the immutable plan is not changed.',
    supported: 'Supported by sources', not_found: 'No answer found in the checked excerpts', conflict: 'Sources contain a conflict',
    openSource: 'Open source citation', sourceTitle: 'Source excerpt', sourceQuote: 'Quote in answer', sourceExcerpt: 'Document excerpt',
    sourceLoading: 'Loading excerpt…', downloadSource: 'Download original document', downloadLoading: 'Preparing download…', closeSource: 'Close',
    sourceUnavailable: 'The source changed or is unavailable; this citation cannot be opened.', sourceError: 'Could not open the source excerpt.', downloadError: 'Could not download the original document.',
  },
} as const;

export default function DocumentWorkbench() {
  const role = useAuthStore((state) => state.user?.role);
  const sessionKey = useAuthStore((state) => `${state.accessToken ?? ''}:${state.user?.user_id ?? ''}:${state.user?.tenant_id ?? ''}`);
  if (!enabled() || role !== 'methodologist') return null;
  return <DocumentWorkbenchInner key={`${sessionKey}:${role}`} />;
}

function DocumentWorkbenchInner() {
  const locale = localeOf(useLanguageStore((state) => state.lang));
  const ui = DOCUMENT_COPY[locale];
  const recoveryCopy = RECOVERY_COPY[locale];
  const uiRef = useRef(ui);
  uiRef.current = ui;
  const [documents, setDocuments] = useState<DocumentCatalogItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [instruction, setInstruction] = useState('');
  const [candidate, setCandidate] = useState<DocumentCandidate>(initialCandidate);
  const [languageConfirmed, setLanguageConfirmed] = useState(false);
  const [reuseReason, setReuseReason] = useState<AIGenerateRequest['reuse_reason']>(null);
  const [plan, setPlan] = useState<DocumentPlan | null>(null);
  const [dialogue, setDialogue] = useState<DocumentDialogueTask | null>(null);
  const [dialogueMessage, setDialogueMessage] = useState('');
  const [dialogueMode, setDialogueMode] = useState<'question' | 'preparation'>('question');
  const [contentMessageRecoveryRequired, setContentMessageRecoveryRequired] = useState(false);
  const [citationDialog, setCitationDialog] = useState<{ exchangeId: string; citation: DocumentContentCitation; excerpt: string | null } | null>(null);
  const [citationLoading, setCitationLoading] = useState(false);
  const [citationDownloading, setCitationDownloading] = useState(false);
  const [citationError, setCitationError] = useState<string | null>(null);
  const [dialogueTasks, setDialogueTasks] = useState<Array<{ id: string; title: string; updated_at: string; plan_id: string | null }>>([]);
  const [dialogueNextBefore, setDialogueNextBefore] = useState<string | null>(null);
  const [dialogueSaving, setDialogueSaving] = useState(false);
  const [planRecoveryRequired, setPlanRecoveryRequired] = useState(false);
  const [confirmRecoveryRequired, setConfirmRecoveryRequired] = useState(false);
  const [taskNotFound, setTaskNotFound] = useState(false);
  const [job, setJob] = useState<AIGenerationJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<'uploading' | 'indexing' | null>(null);
  const [indexAttempt, setIndexAttempt] = useState<number | null>(null);
  const epoch = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const uploadEpoch = useRef(0);
  const uploadController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const catalogController = useRef<AbortController | null>(null);
  const polling = useRef(false);
  const dialogueEpoch = useRef(0);
  const dialoguePaginationController = useRef<AbortController | null>(null);
  const citationController = useRef<AbortController | null>(null);
  const citationDownloadController = useRef<AbortController | null>(null);
  const objectUrls = useRef(new Set<string>());

  const closeCitationDialog = useCallback(() => {
    citationController.current?.abort(); citationController.current = null;
    citationDownloadController.current?.abort(); citationDownloadController.current = null;
    setCitationDialog(null); setCitationLoading(false); setCitationDownloading(false); setCitationError(null);
  }, []);

  const clearStale = useCallback(() => {
    requestController.current?.abort();
    requestController.current = null;
    epoch.current += 1;
    setPending(false);
    setError(null);
    setLanguageConfirmed(false);
    setPlan(null);
    setJob(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('document_plan');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }, []);

  const applyDialogueTask = useCallback(async (task: DocumentDialogueTask, isCurrent: () => boolean, signal?: AbortSignal) => {
    if (!isCurrent()) return;
    setDialogueMessage('');
    setContentMessageRecoveryRequired(false); closeCitationDialog();
    setDialogue(task); setSelected(task.sources.map((source) => source.document_id));
    setInstruction(task.draft.instruction); setCandidate(task.draft.candidate);
    setLanguageConfirmed(task.draft.language_confirmed); setReuseReason(task.draft.reuse_reason);
    setPlan(null); setJob(null); setTaskNotFound(false); setConfirmRecoveryRequired(false);
    setPlanRecoveryRequired(Boolean(task.plan_id));
    if (!task.plan_id) return;
    try {
      const loaded = await loadDocumentPlan(task.plan_id, signal);
      if (!isCurrent()) return;
      setPlan(loaded); setJob(loaded.state === 'submitted' ? loaded.job : null); setPlanRecoveryRequired(false);
    } catch (cause: any) {
      if (isCurrent()) {
        const detail = cause?.response?.data?.detail;
        if (cause?.response?.status === 409 && (detail === 'expired' || detail?.code === 'expired')) {
          setPlan(null); setJob(null); setPlanRecoveryRequired(false);
        } else setPlanRecoveryRequired(true);
      }
    }
  }, [closeCitationDialog]);

  const fetchDocuments = useCallback(async (signal?: AbortSignal) => {
    const response = await api.get<DocumentCatalogResponse>('/v1/documents/catalog?lifecycle_status=active&limit=100', signal ? { signal } : undefined);
    if (!mounted.current || signal?.aborted) return response.data.items;
    setDocuments(response.data.items.filter((item) => item.lifecycle_status === 'active' && (item.index.status === 'ready' || item.index.status === 'partial')));
    return response.data.items;
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    const activeObjectUrls = objectUrls.current;
    catalogController.current = controller;
    void fetchDocuments(controller.signal).catch((cause) => { if (mounted.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.catalogError); });
    return () => { mounted.current = false; controller.abort(); catalogController.current?.abort(); requestController.current?.abort(); uploadController.current?.abort(); citationController.current?.abort(); citationDownloadController.current?.abort(); activeObjectUrls.forEach((url) => URL.revokeObjectURL(url)); activeObjectUrls.clear(); };
  }, [fetchDocuments]);

  useEffect(() => {
    const controller = new AbortController();
    const current = ++dialogueEpoch.current;
    const taskId = new URLSearchParams(window.location.search).get('document_task');
    void Promise.allSettled([listDocumentDialogues(undefined, controller.signal), taskId ? getDocumentDialogue(taskId, controller.signal) : Promise.resolve(null)])
      .then(([listResult, taskResult]) => {
        if (!mounted.current || current !== dialogueEpoch.current) return;
        if (listResult.status === 'fulfilled') { setDialogueTasks(listResult.value.tasks); setDialogueNextBefore(listResult.value.has_more ? listResult.value.next_before : null); }
        const task = taskResult.status === 'fulfilled' ? taskResult.value : null;
        if (taskId && taskResult.status === 'rejected') {
          if (taskResult.reason?.response?.status === 404) setTaskNotFound(true);
          else setError(uiRef.current.taskError);
        }
        if (task) void applyDialogueTask(task, () => mounted.current && current === dialogueEpoch.current && !controller.signal.aborted, controller.signal);
      }).catch((cause) => { if (mounted.current && current === dialogueEpoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.taskError); });
    return () => { controller.abort(); dialoguePaginationController.current?.abort(); dialogueEpoch.current += 1; };
  }, [applyDialogueTask]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has('document_task')) return;
    const planId = new URLSearchParams(window.location.search).get('document_plan');
    if (!planId) return;
    const current = ++epoch.current;
    const controller = new AbortController();
    requestController.current = controller;
    setPending(true);
    void loadDocumentPlan(planId, controller.signal).then((loaded) => {
      if (!mounted.current || current !== epoch.current) return;
      setPlan(loaded);
      if (loaded.state === 'submitted') setJob(loaded.job);
      else {
        const restored = loaded.generation;
        setInstruction(loaded.instruction);
        setCandidate({
          target_audience: restored.target_audience, course_intent: restored.course_intent,
          course_format: restored.course_format, language: restored.language,
          source_strategy: restored.source_strategy, combination_goal: restored.combination_goal,
        });
        setLanguageConfirmed(restored.language_confirmed);
        setReuseReason(restored.reuse_reason ?? null);
        setSelected(restored.documents);
      }
    }).catch((cause) => {
      if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.restoreError);
    }).finally(() => { if (mounted.current && current === epoch.current) setPending(false); });
    return () => { controller.abort(); epoch.current += 1; };
  }, []);

  useEffect(() => {
    if (!job || ['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) return;
    const controller = new AbortController();
    const refresh = async () => {
      if (polling.current || controller.signal.aborted || !mounted.current) return;
      polling.current = true;
      try {
        const response = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(job.id)}`, { signal: controller.signal });
        if (!controller.signal.aborted && mounted.current && response.data.id === job.id) setJob(response.data);
      } catch { /* transient polling errors leave the factual last state visible */ }
      finally { polling.current = false; }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [job]);

  const toggleDocument = (id: string) => {
    if (dialogue) return;
    clearStale();
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length >= 5 ? current : [...current, id]);
  };

  const upload = async (file: File) => {
    const current = ++uploadEpoch.current;
    const controller = new AbortController();
    uploadController.current?.abort(); uploadController.current = controller;
    setUploading(true); setUploadStatus('uploading'); setIndexAttempt(null); setError(null);
    const form = new FormData(); form.append('file', file); form.append('title', file.name.replace(/\.[^/.]+$/, ''));
    try {
      const response = await api.post<{ id: string; indexing_job_id?: string | null }>('/v1/documents/upload', form, { headers: { 'Content-Type': 'multipart/form-data' }, signal: controller.signal });
      if (!mounted.current || current !== uploadEpoch.current) return;
      const jobId = response.data.indexing_job_id;
      if (jobId) {
        let ready = false;
        let indexingFailed = false;
        for (let attempt = 0; attempt < 20 && !controller.signal.aborted; attempt += 1) {
          setUploadStatus('indexing'); setIndexAttempt(attempt + 1);
          const statusResponse: { data: AIGenerationJob } = await api.get<AIGenerationJob>(`/v1/ai/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
          if (!mounted.current || current !== uploadEpoch.current || controller.signal.aborted) return;
          if (statusResponse.data.id !== jobId) throw new Error('Indexing job identity mismatch');
          await fetchDocuments(controller.signal);
          if (!mounted.current || current !== uploadEpoch.current || controller.signal.aborted) return;
          if (['completed', 'failed', 'cancelled', 'interrupted'].includes(statusResponse.data.status)) {
            ready = statusResponse.data.status === 'completed';
            if (!ready) { indexingFailed = true; setError(statusResponse.data.message || uiRef.current.indexingError); }
            break;
          }
          await new Promise<void>((resolve) => window.setTimeout(resolve, 3000));
        }
        if (!ready && !indexingFailed && mounted.current && current === uploadEpoch.current && !controller.signal.aborted) setError(uiRef.current.indexingTimeout);
      } else await fetchDocuments(controller.signal);
      if (mounted.current && current === uploadEpoch.current) { setUploadStatus(null); setIndexAttempt(null); }
    } catch (cause: any) { if (mounted.current && current === uploadEpoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.uploadError); }
    finally { if (mounted.current && current === uploadEpoch.current) { uploadController.current = null; setUploading(false); } }
  };

  const generation = (): AIGenerateRequest => ({ ...candidate, documents: selected, language_confirmed: languageConfirmed, reuse_reason: reuseReason });
  const dialogueDraft = (): DocumentDialogueDraft => ({ instruction, candidate, language_confirmed: languageConfirmed, reuse_reason: reuseReason ?? null });
  const dialogueDraftDirty = Boolean(dialogue && stableJson(dialogueDraft()) !== stableJson(dialogue.draft));
  const dialogueLocator = typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('document_task');
  const setDialogueUrl = (id: string | null) => {
    const url = new URL(window.location.href);
    url.searchParams.delete('document_plan');
    if (id) url.searchParams.set('document_task', id); else url.searchParams.delete('document_task');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  };
  const startDialogue = async () => {
    if (dialogueLocator || selected.length < 1 || selected.length > 5 || pending || dialogueSaving) return;
    dialoguePaginationController.current?.abort();
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null); setTaskNotFound(false);
    const taskId = crypto.randomUUID();
    setPlan(null); setJob(null);
    setDialogueUrl(taskId);
    try {
      const task = await createDocumentDialogue({ task_id: taskId, document_ids: selected, language: candidate.language, draft: dialogueDraft() }, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setDialogue(task); setDialogueUrl(task.id); setDialogueTasks((items) => [{ id: task.id, title: task.sources.map((source) => source.title).join(', '), updated_at: task.updated_at, plan_id: task.plan_id }, ...items.filter((item) => item.id !== task.id)]);
    } catch (cause: any) { if (mounted.current && current === dialogueEpoch.current) setError(uiRef.current.taskError); }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const reloadDialogue = async () => {
    if (!dialogue) return;
    dialoguePaginationController.current?.abort();
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null);
    try {
      const task = await getDocumentDialogue(dialogue.id, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      await applyDialogueTask(task, () => mounted.current && current === dialogueEpoch.current, controller.signal);
    } catch (cause: any) { if (mounted.current && current === dialogueEpoch.current) {
      if (cause?.response?.status === 404) { setDialogue(null); setTaskNotFound(true); setPlanRecoveryRequired(false); setConfirmRecoveryRequired(false); }
      setError(uiRef.current.taskError);
    } }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const saveDialogue = async () => {
    if (!dialogue || pending || dialogueSaving || planRecoveryRequired || confirmRecoveryRequired) return;
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null);
    try {
      const task = await saveDocumentDialogue(dialogue.id, dialogue.revision, dialogueDraft(), dialogue.language, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setDialogue(task); setPlan(null); setDialogueTasks((items) => items.map((item) => item.id === task.id ? { ...item, updated_at: task.updated_at, plan_id: task.plan_id } : item));
    } catch { if (mounted.current && current === dialogueEpoch.current) setError(uiRef.current.taskError); }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const sendDialogueMessage = async () => {
    const askingQuestion = dialogueMode === 'question';
    if (!dialogue || !dialogueMessage.trim() || pending || dialogueSaving || dialogue.pending_request_id || planRecoveryRequired || confirmRecoveryRequired || contentMessageRecoveryRequired || plan?.state === 'submitted' || dialogue.source_stale || (askingQuestion && Boolean(dialogue.plan_id))) return;
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null);
    try {
      const task = askingQuestion
        ? await messageDocumentContentDialogue(dialogue, crypto.randomUUID(), dialogueMessage, controller.signal)
        : await messageDocumentDialogue(dialogue.id, crypto.randomUUID(), dialogue.revision, dialogueMessage, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setDialogue(task); setDialogueMessage('');
      if (askingQuestion) setContentMessageRecoveryRequired(false);
      else if (task.draft) { setCandidate(task.draft.candidate); setLanguageConfirmed(task.draft.language_confirmed); setReuseReason(task.draft.reuse_reason); setInstruction(task.draft.instruction); }
      if (task.plan_id === null) {
        setPlan(null); setJob(null);
        const url = new URL(window.location.href); url.searchParams.delete('document_plan');
        window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
      }
    } catch { if (mounted.current && current === dialogueEpoch.current) {
      if (askingQuestion) setContentMessageRecoveryRequired(true);
      else setError(uiRef.current.taskError);
    } }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const openCitation = async (exchangeId: string, citation: DocumentContentCitation) => {
    if (!dialogue || dialogue.source_stale) return;
    citationController.current?.abort();
    const controller = new AbortController(); citationController.current = controller;
    setCitationDialog({ exchangeId, citation, excerpt: null }); setCitationLoading(true); setCitationError(null);
    try {
      const source = await getDocumentContentSourceExcerpt(dialogue, exchangeId, citation, controller.signal);
      if (!controller.signal.aborted && mounted.current) setCitationDialog({ exchangeId, citation: source.citation, excerpt: source.excerpt });
    } catch { if (!controller.signal.aborted && mounted.current) setCitationError(CONTENT_COPY[locale].sourceError); }
    finally { if (!controller.signal.aborted && mounted.current) setCitationLoading(false); }
  };
  const downloadCitation = async () => {
    if (!dialogue || !citationDialog || dialogue.source_stale) return;
    citationDownloadController.current?.abort();
    const controller = new AbortController(); citationDownloadController.current = controller;
    setCitationDownloading(true); setCitationError(null);
    try {
      const file = await downloadDocumentContentSource(dialogue, citationDialog.exchangeId, citationDialog.citation, controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      const url = URL.createObjectURL(file.blob); objectUrls.current.add(url);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = file.filename; anchor.hidden = true;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => { URL.revokeObjectURL(url); objectUrls.current.delete(url); }, 30000);
    } catch { if (!controller.signal.aborted && mounted.current) setCitationError(CONTENT_COPY[locale].downloadError); }
    finally { if (!controller.signal.aborted && mounted.current) setCitationDownloading(false); }
  };
  const previewSavedDialogue = async () => {
    if (!dialogue || pending || dialogueSaving || planRecoveryRequired || confirmRecoveryRequired) return;
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null);
    try {
      const result = await previewDocumentDialogue(dialogue.id, dialogue.revision, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setDialogue((task) => task?.id === dialogue.id ? { ...task, plan_id: result.plan_id } : task);
      setPlan(result);
      const url = new URL(window.location.href);
      url.searchParams.set('document_task', dialogue.id); url.searchParams.set('document_plan', result.plan_id);
      window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    } catch (cause: any) { if (mounted.current && current === dialogueEpoch.current) {
      const status = cause?.response?.status;
      if (status === undefined || status >= 500) setPlanRecoveryRequired(true);
      setError(uiRef.current.previewError);
    } }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const openDialogue = async (id: string) => {
    dialoguePaginationController.current?.abort();
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null); setTaskNotFound(false);
    try {
      const task = await getDocumentDialogue(id, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setDialogueUrl(task.id);
      await applyDialogueTask(task, () => mounted.current && current === dialogueEpoch.current, controller.signal);
    } catch (cause: any) { if (mounted.current && current === dialogueEpoch.current) {
      if (cause?.response?.status === 404) { setDialogue(null); setTaskNotFound(true); setPlanRecoveryRequired(false); setConfirmRecoveryRequired(false); }
      setError(uiRef.current.taskError);
    } }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const recoverLinkedPlan = async () => {
    if (!dialogue?.plan_id || dialogueSaving) return;
    const current = ++dialogueEpoch.current; const controller = new AbortController(); setDialogueSaving(true); setError(null);
    try {
      const loaded = await loadDocumentPlan(dialogue.plan_id, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current) return;
      setPlan(loaded); setJob(loaded.state === 'submitted' ? loaded.job : null);
      setPlanRecoveryRequired(false); setConfirmRecoveryRequired(false);
    } catch {
      if (mounted.current && current === dialogueEpoch.current) { setPlan(null); setJob(null); setPlanRecoveryRequired(true); }
    } finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const resetDialogue = () => {
    dialoguePaginationController.current?.abort(); dialogueEpoch.current += 1;
    setDialogue(null); setDialogueMessage(''); setDialogueUrl(null); setPlan(null); setJob(null);
    setPlanRecoveryRequired(false); setConfirmRecoveryRequired(false); setContentMessageRecoveryRequired(false); setDialogueMode('question'); closeCitationDialog(); setTaskNotFound(false); setError(null);
  };
  const loadMoreDialogues = async () => {
    if (!dialogueNextBefore || dialogueSaving) return;
    const cursor = dialogueNextBefore;
    dialoguePaginationController.current?.abort();
    const controller = new AbortController(); dialoguePaginationController.current = controller;
    const current = ++dialogueEpoch.current;
    setDialogueSaving(true);
    try {
      const page = await listDocumentDialogues(cursor, controller.signal);
      if (!mounted.current || current !== dialogueEpoch.current || controller.signal.aborted || cursor !== dialogueNextBefore) return;
      setDialogueTasks((items) => [...items, ...page.tasks.filter((task) => !items.some((item) => item.id === task.id))]);
      setDialogueNextBefore(page.has_more ? page.next_before : null);
    } catch { if (mounted.current && current === dialogueEpoch.current && !controller.signal.aborted) setError(uiRef.current.taskError); }
    finally { if (mounted.current && current === dialogueEpoch.current) setDialogueSaving(false); }
  };
  const preview = async () => {
    if (!instruction.trim() || !candidate.course_intent.trim() || selected.length < 1 || selected.length > 5 || pending) return;
    const current = ++epoch.current; const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null); setJob(null); setPlan(null);
    try {
      const result = await previewDocumentPlan({ instruction, generation: generation() }, controller.signal);
      if (mounted.current && current === epoch.current) { setPlan(result); window.history.replaceState(window.history.state, '', `${window.location.pathname}?document_plan=${encodeURIComponent(result.plan_id)}`); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.previewError); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  const confirm = async () => {
    if (!plan || plan.state !== 'preview_ready' || pending || confirmRecoveryRequired || planRecoveryRequired) return;
    const current = ++epoch.current; setPending(true); setError(null);
    try {
      const result = await confirmDocumentPlan(plan);
      if (mounted.current && current === epoch.current) { setPlan(result); setJob(result.job); }
    } catch (cause: any) { if (mounted.current && current === epoch.current) {
      const status = cause?.response?.status;
      if (status === undefined || status >= 500) setConfirmRecoveryRequired(true);
      setError(status === 409 ? uiRef.current.stalePlan : uiRef.current.confirmError);
    } }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  const interpret = async () => {
    if (!instruction.trim() || pending) return;
    clearStale();
    const current = ++epoch.current; const controller = new AbortController(); requestController.current = controller;
    setPending(true); setError(null);
    try {
      const result = await interpretDocument(instruction, candidate.language, controller.signal);
      if (mounted.current && current === epoch.current && result.state === 'interpreted') { setCandidate((value) => ({ ...value, ...result.candidate })); setLanguageConfirmed(false); setPlan(null); }
      if (mounted.current && current === epoch.current && result.state === 'clarification_needed') { setPlan(null); setError(uiRef.current.clarify); }
    } catch (cause: any) { if (mounted.current && current === epoch.current && !['AbortError', 'CanceledError'].includes(cause?.name)) setError(uiRef.current.interpretationError); }
    finally { if (mounted.current && current === epoch.current) setPending(false); }
  };

  return <Card className="mt-6 border-primary/30">
    <CardHeader><CardTitle>{ui.title}</CardTitle><p className="text-sm text-muted-foreground">{ui.description}</p></CardHeader>
    <CardContent className="space-y-4">
      <label className="block text-sm font-medium">{ui.upload}<input type="file" className="mt-2 block w-full text-sm" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>{uploadStatus && <p role="status" className="text-sm text-muted-foreground">{uploadStatus === 'uploading' ? ui.uploading : `${ui.indexing} (${indexAttempt}/20)`}</p>}
      <div className="space-y-2"><p className="text-sm font-medium">{ui.sources} ({selected.length}/5)</p>{documents.length === 0 ? <p className="text-sm text-muted-foreground">{ui.empty}</p> : documents.map((document) => <label key={document.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selected.includes(document.id)} onChange={() => toggleDocument(document.id)} disabled={Boolean(dialogue) || (!selected.includes(document.id) && selected.length >= 5)} />{document.title} <span className="text-xs text-muted-foreground">v{document.version} · {ui.indexStatus[document.index.status as keyof typeof ui.indexStatus] ?? document.index.status}</span></label>)}</div>
      <label className="block text-sm font-medium">{ui.instruction}<textarea value={instruction} onChange={(event) => { clearStale(); setInstruction(event.target.value); }} maxLength={4000} rows={3} className="mt-2 w-full rounded border p-2" /></label><p className="text-xs text-muted-foreground">{ui.instructionHelp}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">{ui.audience}<input value={candidate.target_audience} onChange={(event) => { clearStale(); setCandidate({ ...candidate, target_audience: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">{ui.goal}<input value={candidate.course_intent} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_intent: event.target.value }); }} maxLength={2000} className="mt-1 w-full rounded border p-2" /></label>
        <label className="text-sm">{ui.language}<select value={candidate.language} disabled={Boolean(dialogue)} onChange={(event) => { clearStale(); setCandidate({ ...candidate, language: event.target.value as DocumentCandidate['language'] }); }} className="mt-1 w-full rounded border p-2"><option value="ru">{ui.languages.ru}</option><option value="kk">{ui.languages.kk}</option><option value="en">{ui.languages.en}</option></select></label>
        <label className="text-sm">{ui.format}<select value={candidate.course_format} onChange={(event) => { clearStale(); setCandidate({ ...candidate, course_format: event.target.value as DocumentCandidate['course_format'] }); }} className="mt-1 w-full rounded border p-2"><option value="automatic">{ui.formats.automatic}</option><option value="brief">{ui.formats.brief}</option><option value="standard">{ui.formats.standard}</option><option value="detailed">{ui.formats.detailed}</option></select></label>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={candidate.source_strategy === 'intentional_combination'} onChange={(event) => { clearStale(); setCandidate({ ...candidate, source_strategy: event.target.checked ? 'intentional_combination' : 'single_topic', combination_goal: event.target.checked ? candidate.combination_goal : '' }); }} />{ui.combine}</label>
      {candidate.source_strategy === 'intentional_combination' && <textarea value={candidate.combination_goal} onChange={(event) => { clearStale(); setCandidate({ ...candidate, combination_goal: event.target.value }); }} maxLength={2000} rows={2} placeholder={ui.combinationPlaceholder} className="w-full rounded border p-2 text-sm" />}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={languageConfirmed} onChange={(event) => { clearStale(); setLanguageConfirmed(event.target.checked); }} />{ui.confirmLanguage}</label>
      <label className="text-sm">{ui.reuse}<select value={reuseReason ?? ''} onChange={(event) => { clearStale(); setReuseReason((event.target.value || null) as AIGenerateRequest['reuse_reason']); }} className="mt-1 w-full rounded border p-2">{Object.entries(ui.reuseOptions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <section aria-label={CONTENT_COPY[locale].questionTitle} className="space-y-3 rounded border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{CONTENT_COPY[locale].questionTitle}</h3><div className="flex flex-wrap gap-2">
          {!dialogue && <Button type="button" variant="outline" aria-label={dialogueLocator ? ui.reloadTask : CONTENT_COPY[locale].startQuestionTask} onClick={() => dialogueLocator ? void openDialogue(dialogueLocator) : void startDialogue()} disabled={dialogueSaving || pending || (!dialogueLocator && selected.length < 1)}>{dialogueLocator ? ui.reloadTask : CONTENT_COPY[locale].startQuestionTask}</Button>}
          {dialogue && <><Button type="button" variant="outline" onClick={() => void saveDialogue()} disabled={dialogueSaving || pending || Boolean(dialogue.pending_request_id) || planRecoveryRequired || confirmRecoveryRequired || plan?.state === 'submitted' || !dialogueDraftDirty}>{ui.saveDraft}</Button><Button type="button" variant="outline" onClick={() => void reloadDialogue()} disabled={dialogueSaving}>{ui.reloadTask}</Button>{dialogue.plan_id && (planRecoveryRequired || confirmRecoveryRequired) && <Button type="button" variant="outline" onClick={() => void recoverLinkedPlan()} disabled={dialogueSaving}>{recoveryCopy.recoverPlan}</Button>}<Button type="button" onClick={() => void previewSavedDialogue()} disabled={dialogueSaving || pending || dialogueDraftDirty || planRecoveryRequired || confirmRecoveryRequired || plan?.state === 'submitted' || Boolean(dialogue.pending_request_id) || dialogue.source_stale || Boolean(dialogue.interrupted_request_id)}>{ui.prepare}</Button><Button type="button" variant="outline" onClick={resetDialogue}>{recoveryCopy.newTask}</Button></>}
        </div></div>
        <p className="text-sm text-muted-foreground">{CONTENT_COPY[locale].taskHint}</p>
        {dialogueTasks.length > 0 && <><label className="block text-sm">{ui.recentTasks}<select aria-label={ui.recentTasks} value={dialogue?.id ?? ''} onChange={(event) => { if (event.target.value) void openDialogue(event.target.value); }} className="mt-1 w-full rounded border p-2"><option value="">—</option>{dialogueTasks.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>{dialogueNextBefore && <Button type="button" variant="outline" onClick={() => void loadMoreDialogues()} disabled={dialogueSaving}>{ui.moreTasks}</Button>}</>}
        {taskNotFound && dialogueLocator && <><p role="alert" className="text-sm text-destructive">{recoveryCopy.missing}</p><Button type="button" variant="outline" onClick={resetDialogue}>{recoveryCopy.newTask}</Button></>}
        {dialogue && <>
          <p className="text-xs text-muted-foreground">{ui.task} {dialogue.id} · revision {dialogue.revision}</p>
          {dialogue.source_stale && <p role="alert" className="text-sm text-destructive">{ui.sourceStale}</p>}
          {dialogue.pending_request_id && <p role="status" className="text-sm">{ui.pendingRequest}</p>}
          {dialogue.interrupted_request_id && <p role="status" className="text-sm text-muted-foreground">{recoveryCopy.interruptedRequest}</p>}
          {planRecoveryRequired && <p role="alert" className="text-sm text-destructive">{recoveryCopy.unknownPlan}</p>}
          {confirmRecoveryRequired && <p role="alert" className="text-sm text-destructive">{recoveryCopy.confirmUnknown}</p>}
          {contentMessageRecoveryRequired && <p role="alert" className="text-sm text-destructive">{CONTENT_COPY[locale].questionRecovery}</p>}
          <label className="block text-sm">{CONTENT_COPY[locale].mode}<select aria-label={CONTENT_COPY[locale].mode} value={dialogueMode} onChange={(event) => setDialogueMode(event.target.value as 'question' | 'preparation')} className="mt-1 w-full rounded border p-2"><option value="question">{CONTENT_COPY[locale].questionMode}</option><option value="preparation">{CONTENT_COPY[locale].preparationMode}</option></select></label>
          {dialogueMode === 'question' && dialogue.plan_id && <p role="status" className="text-sm text-muted-foreground">{CONTENT_COPY[locale].planExists}</p>}
<div aria-label={ui.exchanges} className="space-y-2"><p className="text-sm font-medium">{ui.exchanges}</p>{dialogue.exchanges.length === 0 ? <p className="text-sm text-muted-foreground">{ui.noMessages}</p> : dialogue.exchanges.map((exchange) => <article key={exchange.id} className="rounded bg-muted/40 p-2 text-sm"><p>{exchange.instruction}</p><p className="text-xs text-muted-foreground">{exchange.state}</p>{exchange.response?.state === 'interpreted' && <p>{exchange.response.candidate.course_intent || exchange.response.candidate.target_audience}</p>}{exchange.response?.state === 'clarification_needed' && <p>{ui.clarify}</p>}{exchange.response?.state === 'answered' && <div className="mt-2 space-y-2"><p className="font-medium">{CONTENT_COPY[locale][exchange.response.status]}</p><p className="whitespace-pre-wrap">{exchange.response.answer}</p>{exchange.response.citations.map((citation) => <div key={`${exchange.id}-${citation.number}`} className="rounded border p-2"><p className="font-medium">[{citation.number}] {citation.title} · v{citation.version}</p><p className="line-clamp-3 whitespace-pre-wrap">{citation.quote}</p><Button type="button" variant="outline" onClick={() => void openCitation(exchange.id, citation)} disabled={dialogue.source_stale}>{CONTENT_COPY[locale].openSource}</Button></div>)}</div>}</article>)}</div>
          <label className="block text-sm">{ui.dialogue}<textarea aria-label={dialogueMode === 'question' ? CONTENT_COPY[locale].questionPlaceholder : CONTENT_COPY[locale].preparationPlaceholder} value={dialogueMessage} onChange={(event) => setDialogueMessage(event.target.value)} maxLength={4000} rows={2} className="mt-1 w-full rounded border p-2" /></label>
          <Button type="button" variant="outline" onClick={() => void sendDialogueMessage()} disabled={dialogueSaving || pending || !dialogueMessage.trim() || Boolean(dialogue.pending_request_id) || dialogue.source_stale || contentMessageRecoveryRequired || (dialogueMode === 'question' && (Boolean(dialogue.plan_id) || planRecoveryRequired || confirmRecoveryRequired))}>{dialogueMode === 'question' ? CONTENT_COPY[locale].askQuestion : CONTENT_COPY[locale].sendPreparation}</Button>
          {citationDialog && <Modal open onClose={closeCitationDialog} title={CONTENT_COPY[locale].sourceTitle} className="max-w-2xl">
            <p className="mt-1 text-sm font-medium">{citationDialog.citation.title} · v{citationDialog.citation.version}</p>
            <h4 className="mt-3 text-sm font-medium">{CONTENT_COPY[locale].sourceQuote}</h4>
            <p className="whitespace-pre-wrap rounded bg-muted/40 p-2 text-sm">{citationDialog.citation.quote}</p>
            <h4 className="mt-3 text-sm font-medium">{CONTENT_COPY[locale].sourceExcerpt}</h4>
            {citationLoading ? <p role="status">{CONTENT_COPY[locale].sourceLoading}</p> : <p className="whitespace-pre-wrap rounded bg-muted/40 p-2 text-sm">{citationDialog.excerpt ?? CONTENT_COPY[locale].sourceUnavailable}</p>}
            {citationError && <p role="alert" className="text-sm text-destructive">{citationError}</p>}
            <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center"><Button type="button" className="h-auto min-h-10 w-full whitespace-normal sm:w-auto" onClick={() => void downloadCitation()} disabled={citationDownloading || citationLoading || !citationDialog.excerpt || dialogue.source_stale}>{citationDownloading ? CONTENT_COPY[locale].downloadLoading : CONTENT_COPY[locale].downloadSource}</Button><Button type="button" variant="outline" className="h-auto min-h-10 w-full whitespace-normal sm:w-auto" onClick={closeCitationDialog}>{CONTENT_COPY[locale].closeSource}</Button></div>
          </Modal>}
        </>}
      </section>
      <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => void interpret()} disabled={pending || Boolean(dialogue) || !instruction.trim()}>{ui.interpret}</Button><Button type="button" onClick={() => void preview()} disabled={pending || Boolean(dialogue) || !instruction.trim() || !candidate.course_intent.trim() || selected.length < 1}>{ui.prepare}</Button></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {plan?.state === 'preview_ready' && <PreviewCard preview={plan} pending={pending || confirmRecoveryRequired || planRecoveryRequired} onConfirm={() => void confirm()} ui={ui} locale={locale} />}
      {job && <JobCard job={job} ui={ui} />}
    </CardContent>
  </Card>;
}

function PreviewCard({ preview, pending, onConfirm, ui, locale }: { preview: DocumentPreview; pending: boolean; onConfirm: () => void; ui: typeof DOCUMENT_COPY[DocumentLocale]; locale: DocumentLocale }) {
  const generation = preview.generation;
  return <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"><p className="font-medium">{ui.previewReady} {preview.revision}</p><dl className="mt-2 grid gap-1 sm:grid-cols-2"><div><dt className="text-xs text-muted-foreground">{ui.audience}</dt><dd>{generation.target_audience || ui.audienceMissing}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.goal}</dt><dd>{generation.course_intent || ui.audienceMissing}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.language}</dt><dd>{ui.languages[generation.language]}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.format}</dt><dd>{ui.formats[generation.course_format]}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.combine}</dt><dd>{generation.source_strategy === 'intentional_combination' ? generation.combination_goal : ui.combinationNone}</dd></div><div><dt className="text-xs text-muted-foreground">{ui.reuse}</dt><dd>{generation.reuse_reason ? ui.reuseOptions[generation.reuse_reason] : ui.reuseMissing}</dd></div></dl><p className="mt-2">{ui.sourcesList} {preview.sources.map((source) => `${source.title} v${source.version}`).join(', ')}</p><p>{ui.validUntil} {new Date(preview.expires_at).toLocaleString({ ru: 'ru-RU', kk: 'kk-KZ', en: 'en-US' }[locale])}</p><p className="text-xs text-muted-foreground">{ui.fingerprint} {preview.fingerprint}</p><Button className="mt-3" type="button" onClick={onConfirm} disabled={pending}>{ui.confirm}</Button></div>;
}

function JobCard({ job, ui }: { job: AIGenerationJob; ui: typeof DOCUMENT_COPY[DocumentLocale] }) {
  const done = job.status === 'completed' && job.course_id;
  const errors = Array.isArray((job as AIGenerationJob & { errors?: Array<string | { message?: string }> }).errors)
    ? (job as AIGenerationJob & { errors: Array<string | { message?: string }> }).errors.map((item: string | { message?: string }) => typeof item === 'string' ? item : item.message || JSON.stringify(item)).join('; ')
    : '';
  return <div className="rounded border p-3 text-sm" role="status" aria-live="polite"><p className="font-medium">{ui.task} {job.status}</p><p>{job.message || `${ui.stage} ${job.stage || ui.noStage}`} · {ui.progress} {job.progress}%</p>{errors && <p role="alert" className="mt-1 text-destructive">{errors}</p>}{done && <div className="mt-2 flex gap-3"><a className="text-primary underline" href={`/courses/${job.course_id}/edit`}>{ui.openCourse}</a><a className="text-primary underline" href={`/ai/generate?job_id=${encodeURIComponent(job.id)}`}>{ui.openGeneration}</a></div>}</div>;
}
