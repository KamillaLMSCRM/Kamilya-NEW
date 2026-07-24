'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Card, CardContent, Button, Badge, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { getAccessToken } from '@/lib/auth';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { CheckCircle2, Circle, Lightbulb, ChevronRight, ChevronDown } from 'lucide-react';
import { QuizAssignPanel } from '@/features/quiz-assignments';
import { firstQuizForAssignments } from './assignment-deep-link';

interface QuizChoice {
  id: string;
  text: string;
  is_correct: boolean;
  order_index: number;
}

interface Question {
  id: string;
  text: string;
  type: string;
  points: number;
  explanation: string | null;
  order_index: number;
  choices: QuizChoice[];
}

interface Quiz {
  id: string;
  lesson_id: string;
  title: string;
  pass_score: number;
  time_limit: number | null;
  attempt_limit: number;
  deferral_days: number;
  questions: Question[];
}

// Response shape of GET /v1/quizzes/grouped. The backend returns the full
// course → module → lesson tree with each lesson carrying its quiz (if any),
// plus a flat orphans list for quizzes whose lesson was deleted or nulled.
interface GroupedLesson {
  id: string;
  title: string;
  order_index: number;
  quiz: Quiz | null;
}

interface GroupedModule {
  id: string;
  title: string;
  order_index: number;
  lessons: GroupedLesson[];
}

interface GroupedCourse {
  id: string;
  title: string;
  status: string;
  modules: GroupedModule[];
}

interface OrphanQuiz {
  quiz: Quiz;
  lesson_id: string | null;
}

interface QuizGroupedResponse {
  courses: GroupedCourse[];
  orphans: OrphanQuiz[];
}

export default function QuizzesAdminPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [grouped, setGrouped] = useState<QuizGroupedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedQuiz, setSelectedQuiz] = useState<Quiz | null>(null);
  const assignmentDeepLinkHandled = useRef(false);
  const assignmentScrollPending = useRef(false);
  const [editing, setEditing] = useState(false);
  // Cascade selector state — Course → Module → Lesson. Replaces the old
  // free-form "Lesson ID (UUID)" input that forced methodologists to
  // look up UUIDs in the database, which was a usability dead end.
  // Source of truth for the selector is `grouped` (server-provided tree),
  // so no separate state for courses/previews is needed.
  const [openCourses, setOpenCourses] = useState<Record<string, boolean>>({});
  const [newQuiz, setNewQuiz] = useState({
    course_id: '',
    module_id: '',
    lesson_id: '',
    title: '',
    pass_score: 80,
    time_limit: '',
    attempt_limit: 3,
  });
  const [newQuestion, setNewQuestion] = useState({ text: '', type: 'MCQ', points: 1, explanation: '' });
  const [newChoices, setNewChoices] = useState<Array<{ text: string; is_correct: boolean }>>([
    { text: '', is_correct: false },
    { text: '', is_correct: false },
    { text: '', is_correct: false },
    { text: '', is_correct: false },
  ]);
  const [showCreateQuiz, setShowCreateQuiz] = useState(false);
  const [showAddQuestion, setShowAddQuestion] = useState(false);
  // Inline edit form for pass_score / attempt_limit / time_limit.
  // Previously these were visible-only ("readonly" labels) — adding
  // the edit form is the change requested in the 2026-06-26 review.
  const [editingSettings, setEditingSettings] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<{
    pass_score: number;
    time_limit: string; // empty string == unlimited, kept as string for the input
    attempt_limit: number;
  }>({ pass_score: 80, time_limit: '', attempt_limit: 3 });
  const [savingSettings, setSavingSettings] = useState(false);
  // AI draft state. When the methodologist clicks "Generate with AI",
  // we POST /v1/quizzes/generate and stash the draft here so they can
  // review/edit questions before saving. The draft is NEVER persisted
  // to the DB until the methodologist explicitly clicks Save — this
  // is the whole point of having a review step.
  const [aiDraft, setAiDraft] = useState<{
    lesson_id: string;
    suggested_title: string;
    suggested_pass_score: number;
    questions: Array<{
      text: string;
      type: string;
      points: number;
      explanation: string | null;
      order_index: number;
      choices: Array<{ text: string; is_correct: boolean }>;
    }>;
    latency_ms?: number;
  } | null>(null);
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiDifficulty, setAiDifficulty] = useState<'easy' | 'medium' | 'hard'>('medium');
  const [aiGuidance, setAiGuidance] = useState('');
  const token = useAuthStore((s) => s.accessToken);
  // Initialize the auth store from localStorage on mount. Without this,
  // if the user refreshes the page (or navigates directly to /quizzes
  // without going through the Layout's useEffect), token is null until
  // Layout re-runs initialize(). This is a no-op if already initialized.
  const initialize = useAuthStore((s) => s.initialize);
  useEffect(() => {
    initialize();
  }, [initialize]);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  // Single request fetches the entire cascade tree (course → module →
  // lesson → quiz) plus orphans. Replaces the previous two-request flow
  // (`/v1/courses` + lazy `/v1/courses/{id}/preview`) which left quizzes
  // in a misleading "orphan" bucket until previews loaded.
  const fetchGrouped = useCallback(async () => {
    // Fallback to localStorage in case Zustand hasn't been initialized
    // yet (e.g. direct page load bypassing Layout's useEffect).
    const authToken = token || getAccessToken();
    if (!authToken) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/quizzes/grouped`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) setGrouped(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => { fetchGrouped(); }, [fetchGrouped]);

  // Flat list of every quiz, regardless of placement in the tree. Used
  // by the "Тесты" badge count and by the orphan-less delete handler
  // (e.g. handleDeleteQuiz just needs `flatQuizzes.find(...)`). With the
  // server-provided tree this is a pure projection — no N+1, no merging.
  const flatQuizzes = useMemo(() => {
    if (!grouped) return [];
    return grouped.courses.flatMap((c) =>
      c.modules.flatMap((m) =>
        m.lessons.flatMap((l) => (l.quiz ? [l.quiz] : []))
      )
    );
  }, [grouped]);

  useEffect(() => {
    if (!grouped || assignmentDeepLinkHandled.current) return;
    if (new URLSearchParams(window.location.search).get('section') !== 'assignments') return;

    assignmentDeepLinkHandled.current = true;
    const firstQuiz = firstQuizForAssignments(grouped);
    if (firstQuiz) {
      assignmentScrollPending.current = true;
      setSelectedQuiz(firstQuiz);
    }
  }, [grouped]);

  useEffect(() => {
    if (!selectedQuiz || !assignmentScrollPending.current) return;
    assignmentScrollPending.current = false;
    document.getElementById('assignments')?.scrollIntoView({ block: 'start' });
  }, [selectedQuiz]);

  // Resolve the course currently selected in the create-quiz cascade
  // from the server-provided tree. Replaces the old `previews[course_id]`
  // lookup, since with the grouped endpoint we already have all modules
  // and lessons in memory — no per-course fetch needed.
  const selectedCourseInForm = useMemo(
    () => grouped?.courses.find((c) => c.id === newQuiz.course_id) ?? null,
    [grouped, newQuiz.course_id]
  );

  const handleCreateQuiz = async () => {
    if (!token || !newQuiz.lesson_id || !newQuiz.title) return;
    const res = await fetch(`${API_URL}/v1/quizzes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
      body: JSON.stringify({
        lesson_id: newQuiz.lesson_id,
        title: newQuiz.title,
        pass_score: newQuiz.pass_score,
        time_limit: newQuiz.time_limit ? parseInt(newQuiz.time_limit) : null,
        attempt_limit: newQuiz.attempt_limit,
      }),
    });
    if (res.ok) {
      const quiz = await res.json();
      setSelectedQuiz(quiz);
      setShowCreateQuiz(false);
      setNewQuiz({
        course_id: '',
        module_id: '',
        lesson_id: '',
        title: '',
        pass_score: 80,
        time_limit: '',
        attempt_limit: 3,
      });
      // Refresh the tree so the new quiz appears under the chosen lesson.
      await fetchGrouped();
    } else {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      toast.error(`Не удалось создать тест: ${err.detail || `HTTP ${res.status}`}`);
    }
  };

  // Call POST /v1/quizzes/generate — backend calls the LLM (Qwen on DGX,
  // falls back to DeepSeek) and returns a draft. We do NOT save yet;
  // the methodologist reviews in the preview modal first.
  const handleGenerateWithAI = async () => {
    if (!token || !newQuiz.lesson_id) return;
    setAiGenerating(true);
    try {
      const res = await fetch(`${API_URL}/v1/quizzes/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
        body: JSON.stringify({
          lesson_id: newQuiz.lesson_id,
          num_questions: 8,
          difficulty: aiDifficulty,
          language: 'ru',
          guidance: aiGuidance.trim() || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const draft = await res.json();
      setAiDraft(draft);
      // Pre-fill the create form with the AI's suggested values so the
      // methodologist can tweak before saving.
      setNewQuiz((p) => ({
        ...p,
        title: draft.suggested_title,
        pass_score: draft.suggested_pass_score,
      }));
    } catch (e) {
      toast.error(`AI-генерация не удалась: ${(e as Error).message}`);
    } finally {
      setAiGenerating(false);
    }
  };

  // Persist the AI draft as a real Quiz + Questions. We do this in two
  // calls because the existing POST /v1/quizzes schema doesn't accept
  // questions inline. POST returns the empty quiz; we then POST each
  // question one at a time. (Acceptable trade-off — methodologist is
  // already reviewing the draft at this point, the latency is fine.)
  const handleSaveAiDraft = async () => {
    if (!aiDraft || !token) return;
    if (!newQuiz.lesson_id) {
      toast.error('Сначала выберите урок');
      return;
    }
    setAiGenerating(true);
    try {
      // 1. Create the empty quiz shell.
      const createRes = await fetch(`${API_URL}/v1/quizzes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
        body: JSON.stringify({
          lesson_id: newQuiz.lesson_id,
          title: newQuiz.title || aiDraft.suggested_title,
          pass_score: newQuiz.pass_score,
          time_limit: newQuiz.time_limit ? parseInt(newQuiz.time_limit) : null,
          attempt_limit: newQuiz.attempt_limit,
        }),
      });
      if (!createRes.ok) {
        const err = await createRes.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${createRes.status}`);
      }
      const quiz = await createRes.json();

      // 2. Add each question. Failures here leave a partial quiz — the
      // methodologist can edit/clean it up via the regular UI.
      let added = 0;
      for (const q of aiDraft.questions) {
        const qRes = await fetch(`${API_URL}/v1/quizzes/${quiz.id}/questions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
          body: JSON.stringify({
            text: q.text,
            type: q.type,
            points: q.points,
            explanation: q.explanation,
            order_index: q.order_index,
            choices: q.choices.map((c, i) => ({
              text: c.text,
              is_correct: c.is_correct,
              order_index: i,
            })),
          }),
        });
        if (qRes.ok) added++;
      }

      // 3. Refresh everything.
      setAiDraft(null);
      setShowCreateQuiz(false);
      setAiGuidance('');
      await fetchGrouped();
      toast.success(`Тест создан: ${added} из ${aiDraft.questions.length} вопросов добавлено`);
    } catch (e) {
      toast.error(`Не удалось сохранить: ${(e as Error).message}`);
    } finally {
      setAiGenerating(false);
    }
  };

  const handleAddQuestion = async () => {
    if (!token || !selectedQuiz || !newQuestion.text) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${selectedQuiz.id}/questions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
      body: JSON.stringify({
        ...newQuestion,
        order_index: selectedQuiz.questions.length,
        choices: newChoices.filter((c) => c.text.trim()).map((c, i) => ({
          text: c.text,
          is_correct: c.is_correct,
          order_index: i,
        })),
      }),
    });
    if (res.ok) {
      const quiz = await res.json();
      setSelectedQuiz(quiz);
      setShowAddQuestion(false);
      setNewQuestion({ text: '', type: 'MCQ', points: 1, explanation: '' });
      setNewChoices([
        { text: '', is_correct: false },
        { text: '', is_correct: false },
        { text: '', is_correct: false },
        { text: '', is_correct: false },
      ]);
    }
  };

  const handleDeleteQuestion = async (questionId: string) => {
        if (!token || !selectedQuiz) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteQuestion'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${selectedQuiz.id}/questions/${questionId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token || getAccessToken()}` },
    });
    if (res.ok) {
      const quiz = await res.json();
      setSelectedQuiz(quiz);
    }
  };

  const handleDeleteQuiz = async (quizId: string) => {
        if (!token) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteQuiz'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${quizId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token || getAccessToken()}` },
    });
    if (res.ok) {
      setSelectedQuiz(null);
      await fetchGrouped();
    }
  };

  // Start editing pass_score / time_limit / attempt_limit for the
  // currently selected quiz. Pre-fills from the live quiz object so
  // the user sees current values in the inputs.
  const startEditSettings = (quiz: Quiz) => {
    setSettingsDraft({
      pass_score: quiz.pass_score,
      time_limit: quiz.time_limit != null ? String(quiz.time_limit) : '',
      attempt_limit: quiz.attempt_limit,
    });
    setEditingSettings(true);
  };

  // Persist the edited settings via PUT /v1/quizzes/{id}. Backend
  // already supports partial updates on these three fields — see
  // Pydantic QuizUpdate in app.modules.quizzes.schemas.
  const handleSaveQuizSettings = async () => {
    if (!selectedQuiz || !token) return;
    setSavingSettings(true);
    try {
      const body: Record<string, unknown> = {
        pass_score: settingsDraft.pass_score,
        attempt_limit: settingsDraft.attempt_limit,
      };
      const tl = settingsDraft.time_limit.trim();
      if (tl === '') {
        body.time_limit = null;
      } else {
        const n = parseInt(tl, 10);
        if (!Number.isFinite(n) || n <= 0) {
          toast.error('Время должно быть положительным числом минут или пустым');
          return;
        }
        body.time_limit = n;
      }
      const res = await fetch(`${API_URL}/v1/quizzes/${selectedQuiz.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token || getAccessToken()}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const updated = await res.json();
      // Keep the selected detail in sync without a full tree refetch.
      setSelectedQuiz(updated);
      // Patch the in-memory tree so the list panel reflects the new
      // pass_score / time_limit / attempt_limit immediately.
      setGrouped((g) => {
        if (!g) return g;
        return {
          ...g,
          courses: g.courses.map((c) => ({
            ...c,
            modules: c.modules.map((m) => ({
              ...m,
              lessons: m.lessons.map((l) =>
                l.quiz && l.quiz.id === updated.id
                  ? { ...l, quiz: updated }
                  : l
              ),
            })),
          })),
          orphans: g.orphans.map((o) =>
            o.quiz.id === updated.id ? { ...o, quiz: updated } : o
          ),
        };
      });
      setEditingSettings(false);
      toast.success('Параметры теста сохранены');
    } catch (e) {
      toast.error(`Не удалось сохранить: ${(e as Error).message}`);
    } finally {
      setSavingSettings(false);
    }
  };

  // (Removed dev-only "Load quiz by ID" handler — the grouped list panel
// is the only supported way to pick a quiz now. Methodologists don't
// have access to UUIDs without opening the database.)

  return (
    <div className="mx-auto max-w-[1560px] space-y-5 px-1">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-4xl">
          {/* Page header renamed on 2026-06-27 from "Тест — Админ" to
              "Конструктор тестов" — the old label sounded like an admin
              operations panel, but this is actually a content-construction
              page where the methodologist authors quiz questions. The
              subtitle clarifies the workflow: pick a lesson → write/AI the
              questions → save. */}
          <h1 className="text-[26px] font-semibold tracking-normal text-foreground">Конструктор тестов</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            Создание и редактирование тестов. Выберите урок → добавьте вопросы вручную или сгенерируйте черновик из контента урока с помощью AI.
          </p>
        </div>
        <Button onClick={() => setShowCreateQuiz(!showCreateQuiz)} className="h-11 px-5">
          {t('common.create')} {t('quiz.title')}
        </Button>
      </div>

      {/* Create Quiz Form */}
      {showCreateQuiz && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <h3 className="font-semibold">{t('common.create')} {t('quiz.title')}</h3>
            {/* Cascade selector: Курс → Модуль → Урок.
                The old free-form Lesson ID input was a usability dead end
                — methodologists had no way to discover the UUID. We now
                use the tree returned by GET /v1/quizzes/grouped (already
                loaded into `grouped`) to enumerate lessons in the chosen
                course, marking ones that already have a quiz so we don't
                accidentally create a second quiz for the same lesson. */}
            <div className="grid md:grid-cols-3 gap-2">
              <div>
                <label className="text-sm text-muted-foreground">Курс</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={newQuiz.course_id}
                  onChange={(e) => {
                    const cid = e.target.value;
                    setNewQuiz((p) => ({ ...p, course_id: cid, module_id: '', lesson_id: '' }));
                  }}
                >
                  <option value="">— выберите курс —</option>
                  {grouped?.courses.map((c) => (
                    <option key={c.id} value={c.id}>{c.title}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-muted-foreground">Модуль</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={newQuiz.module_id}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, module_id: e.target.value, lesson_id: '' }))}
                  disabled={!newQuiz.course_id}
                >
                  <option value="">— выберите модуль —</option>
                  {selectedCourseInForm?.modules.map((m) => (
                    <option key={m.id} value={m.id}>{m.title}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm text-muted-foreground">Урок</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={newQuiz.lesson_id}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, lesson_id: e.target.value }))}
                  disabled={!newQuiz.module_id}
                >
                  <option value="">— выберите урок —</option>
                  {selectedCourseInForm?.modules
                    .find((m) => m.id === newQuiz.module_id)
                    ?.lessons.map((l) => (
                      <option key={l.id} value={l.id} disabled={l.quiz != null}>
                        {l.title}{l.quiz ? ' (уже есть тест)' : ''}
                      </option>
                    ))}
                </select>
              </div>
            </div>
            <Input
              placeholder={t('courses.courseTitle')}
              value={newQuiz.title}
              onChange={(e) => setNewQuiz((p) => ({ ...p, title: e.target.value }))}
            />
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-sm text-muted-foreground">{t('quiz.passScore')}</label>
                <Input
                  type="number"
                  value={newQuiz.pass_score}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, pass_score: parseInt(e.target.value) || 80 }))}
                />
              </div>
              <div>
                <label className="text-sm text-muted-foreground">{t('quiz.timeLeft')} (мин)</label>
                <Input
                  type="number"
                  placeholder="∞"
                  value={newQuiz.time_limit}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, time_limit: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-sm text-muted-foreground">Лимит попыток</label>
                <Input
                  type="number"
                  value={newQuiz.attempt_limit}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, attempt_limit: parseInt(e.target.value) || 3 }))}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={handleCreateQuiz}
                disabled={!newQuiz.lesson_id || !newQuiz.title}
              >
                {t('common.create')}
              </Button>
              <Button variant="outline" onClick={() => setShowCreateQuiz(false)}>{t('common.cancel')}</Button>
            </div>

            {/* AI assistant — generate a draft quiz from the lesson content.
                The methodologist reviews the draft in a preview modal before
                saving. Backend POST /v1/quizzes/generate returns ~10s on Qwen
                self-hosted, with DeepSeek fallback if Qwen is down. We do NOT
                auto-save — the AI might write nonsense questions about
                content that wasn't in the lesson.
                Gated on 2026-06-27: only show this section once a lesson is
                picked. Before that, the AI has no source material to work
                from, so the section was just noise that confused the
                methodologist about what the button does. */}
            {newQuiz.lesson_id ? (
              <div className="mt-3 pt-3 border-t border-border/50">
                <div className="flex items-center gap-2 mb-2">
                  <Lightbulb size={14} className="text-amber-500" />
                  <span className="text-sm font-medium">Или сгенерировать черновик с AI</span>
                </div>
                <div className="grid grid-cols-2 gap-2 mb-2">
                  <div>
                    <label className="text-xs text-muted-foreground">Сложность</label>
                    <select
                      className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
                      value={aiDifficulty}
                      onChange={(e) => setAiDifficulty(e.target.value as 'easy' | 'medium' | 'hard')}
                      disabled={aiGenerating}
                    >
                      <option value="easy">Лёгкий (онбординг)</option>
                      <option value="medium">Средний</option>
                      <option value="hard">Сложный (senior)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Пожелания (опц.)</label>
                    <Input
                      placeholder="например: фокус на штрафы"
                      value={aiGuidance}
                      onChange={(e) => setAiGuidance(e.target.value)}
                      disabled={aiGenerating}
                    />
                  </div>
                </div>
                <Button
                  variant="secondary"
                  onClick={handleGenerateWithAI}
                  disabled={!newQuiz.lesson_id || aiGenerating}
                  className="w-full"
                >
                  {aiGenerating ? 'Генерируем черновик…' : '✨ Сгенерировать черновик'}
                </Button>
                {aiDraft && (
                  <p className="text-xs text-muted-foreground mt-2">
                    Черновик готов ({aiDraft.questions.length} вопросов
                    {aiDraft.latency_ms ? `, ${(aiDraft.latency_ms / 1000).toFixed(1)}с` : ''}).
                    Прокрутите вниз, чтобы посмотреть и сохранить.
                  </p>
                )}
              </div>
            ) : (
              <div className="mt-3 pt-3 border-t border-border/50 rounded-lg bg-muted/40 px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <Lightbulb size={14} className="text-muted-foreground mt-0.5 shrink-0" />
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">AI-черновик:</span>{' '}
                    выберите урок выше — AI прочитает его контент и предложит вопросы. Без выбранного урока генерация невозможна.
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* AI draft preview. Rendered as a full-width section (not a modal)
          so the methodologist can scroll through all questions at once
          and edit fields inline. We deliberately keep this as a Card,
          not a Modal — the questions are too long for a typical modal
          viewport. */}
      {aiDraft && (
        <Card className="border-amber-300 dark:border-amber-700">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lightbulb size={16} className="text-amber-500" />
                <h3 className="font-semibold">
                  Черновик от AI — проверьте перед сохранением
                </h3>
              </div>
              <button
                type="button"
                className="text-sm text-muted-foreground hover:underline"
                onClick={() => setAiDraft(null)}
              >
                Отклонить
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              {aiDraft.questions.length} вопросов
              {aiDraft.latency_ms ? `, сгенерировано за ${(aiDraft.latency_ms / 1000).toFixed(1)}с` : ''}.
              AI мог ошибиться в формулировках или фактах — обязательно проверьте каждый вопрос.
            </p>
            <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {aiDraft.questions.map((q, qi) => (
                <div
                  key={qi}
                  className="border border-border/60 rounded-md p-3 space-y-2"
                >
                  <div className="flex items-start gap-2">
                    <Badge variant="outline">{qi + 1}</Badge>
                    <textarea
                      className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-sm"
                      value={q.text}
                      onChange={(e) => {
                        const v = e.target.value;
                        setAiDraft((d) =>
                          d
                            ? {
                                ...d,
                                questions: d.questions.map((qq, i) =>
                                  i === qi ? { ...qq, text: v } : qq
                                ),
                              }
                            : d
                        );
                      }}
                      rows={2}
                    />
                  </div>
                  <div className="pl-7 space-y-1">
                    {q.choices.map((ch, ci) => (
                      <label
                        key={ci}
                        className="flex items-start gap-2 text-sm cursor-pointer"
                      >
                        <input
                          type="radio"
                          name={`ai-q-${qi}`}
                          checked={ch.is_correct}
                          onChange={() => {
                            setAiDraft((d) =>
                              d
                                ? {
                                    ...d,
                                    questions: d.questions.map((qq, i) =>
                                      i === qi
                                        ? {
                                            ...qq,
                                            choices: qq.choices.map((cc, j) => ({
                                              ...cc,
                                              is_correct: j === ci,
                                            })),
                                          }
                                        : qq
                                    ),
                                  }
                                : d
                            );
                          }}
                          className="mt-1"
                        />
                        <input
                          type="text"
                          className="flex-1 rounded border border-input bg-background px-2 py-1 text-sm"
                          value={ch.text}
                          onChange={(e) => {
                            const v = e.target.value;
                            setAiDraft((d) =>
                              d
                                ? {
                                    ...d,
                                    questions: d.questions.map((qq, i) =>
                                      i === qi
                                        ? {
                                            ...qq,
                                            choices: qq.choices.map((cc, j) =>
                                              j === ci ? { ...cc, text: v } : cc
                                            ),
                                          }
                                        : qq
                                    ),
                                  }
                                : d
                            );
                          }}
                        />
                      </label>
                    ))}
                  </div>
                  {q.explanation && (
                    <div className="pl-7 text-xs text-muted-foreground">
                      💡 {q.explanation}
                    </div>
                  )}
                  <button
                    type="button"
                    className="text-xs text-destructive hover:underline pl-7"
                    onClick={() => {
                      setAiDraft((d) =>
                        d
                          ? {
                              ...d,
                              questions: d.questions.filter((_, i) => i !== qi),
                            }
                          : d
                      );
                    }}
                  >
                    Удалить вопрос
                  </button>
                </div>
              ))}
            </div>
            <div className="flex gap-2 pt-2 border-t border-border/50">
              <Button onClick={handleSaveAiDraft} disabled={aiGenerating}>
                {aiGenerating ? 'Сохраняем…' : 'Сохранить тест'}
              </Button>
              <Button variant="outline" onClick={() => setAiDraft(null)}>
                Отклонить
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
        {/* Quiz list — grouped by Course → Module → Lesson.
            Data source is `grouped` (the response from GET /v1/quizzes/grouped).
            Each course row shows its quiz count; lessons without a quiz are
            skipped so we don't render empty rows. Orphans surface as their
            own bucket (real orphans: lesson deleted or FK nulled). */}
        <Card className="overflow-hidden border-border/70 shadow-none">
          <CardContent className="p-0">
            <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Тесты</h3>
              <Badge variant="secondary" className="bg-muted text-foreground">{flatQuizzes.length}</Badge>
            </div>
            {loading ? (
              <p className="px-4 py-5 text-sm text-muted-foreground">Загрузка…</p>
            ) : grouped && grouped.courses.every((c) => c.modules.every((m) => m.lessons.every((l) => !l.quiz))) && grouped.orphans.length === 0 ? (
              <p className="px-4 py-5 text-sm leading-6 text-muted-foreground">
                Тестов пока нет. Нажмите «Создать тест» выше.
              </p>
            ) : (
              <div className="max-h-[calc(100vh-280px)] space-y-1 overflow-y-auto p-3">
                {grouped?.courses.map((course) => {
                  const isOpen = openCourses[course.id] ?? true;
                  const moduleRows = course.modules
                    .map((m) => ({
                      module: m,
                      lessons: m.lessons.filter((l) => l.quiz),
                    }))
                    .filter((mb) => mb.lessons.length > 0);
                  const quizCount = moduleRows.reduce((acc, mb) => acc + mb.lessons.length, 0);
                  if (quizCount === 0) return null;
                  return (
                    <div key={course.id} className="rounded-md border border-border/60 bg-background">
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setOpenCourses((p) => ({ ...p, [course.id]: !isOpen }))}
                      >
                        {isOpen ? <ChevronDown size={15} className="text-muted-foreground" /> : <ChevronRight size={15} className="text-muted-foreground" />}
                        <span className="min-w-0 flex-1 truncate">{course.title}</span>
                        <Badge variant="outline" className="border-border bg-card text-muted-foreground">{quizCount}</Badge>
                      </button>
                      {isOpen && (
                        <div className="space-y-2 px-3 pb-3">
                          {moduleRows.map(({ module, lessons }) => (
                            <div key={module.id}>
                              <div className="px-1 py-1.5 text-[11px] font-semibold uppercase leading-4 tracking-wide text-muted-foreground">
                                {module.title}
                              </div>
                              {lessons.map((l) => {
                                const quiz = l.quiz!;
                                return (
                                  <div
                                    key={quiz.id}
                                    className={`cursor-pointer rounded-md px-3 py-2 text-sm transition-colors ${
                                      selectedQuiz?.id === quiz.id ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-muted/70'
                                    }`}
                                    onClick={() => setSelectedQuiz(quiz)}
                                  >
                                    <div className="flex items-center gap-2">
                                      <Circle size={9} className="shrink-0 text-muted-foreground" />
                                      <span className="min-w-0 flex-1 truncate">{l.title}</span>
                                      <Badge variant="secondary" className="ml-2 bg-primary/10 text-primary">{quiz.questions.length}</Badge>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {grouped && grouped.orphans.length > 0 && (
                  <div className="mt-2 rounded-md border border-dashed border-border/70 bg-background">
                    <div className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      Без привязки
                    </div>
                    {grouped.orphans.map(({ quiz }) => (
                      <div
                        key={quiz.id}
                        className={`cursor-pointer rounded-md px-3 py-2 text-sm ${
                          selectedQuiz?.id === quiz.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted/70'
                        }`}
                        onClick={() => setSelectedQuiz(quiz)}
                      >
                        <div className="flex items-center gap-2">
                          <Circle size={10} className="shrink-0" />
                          <span className="min-w-0 flex-1 truncate">{quiz.title}</span>
                          <Badge variant="secondary" className="ml-2 bg-primary/10 text-primary">{quiz.questions.length}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Selected Quiz */}
        {selectedQuiz ? (
          <div className="min-w-0 space-y-5">
            <Card className="border-border/70 shadow-none">
              <CardContent className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="truncate text-xl font-semibold leading-7 text-foreground">{selectedQuiz.title}</h3>
                    <div className="mt-2 text-sm text-muted-foreground">
                      {selectedQuiz.questions.length} вопросов · {selectedQuiz.questions.reduce((a, q) => a + q.points, 0)} баллов
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {!editingSettings && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-9"
                        onClick={() => startEditSettings(selectedQuiz)}
                      >
                        Изменить параметры
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => handleDeleteQuiz(selectedQuiz.id)}
                    >
                      {t('common.delete')}
                    </Button>
                  </div>
                </div>
                <div className="mt-5 grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
                  {editingSettings ? (
                    <>
                      <label className="flex flex-col gap-1">
                        <span className="text-muted-foreground">{t('quiz.passScore')}, %</span>
                        <Input
                          type="number"
                          min={1}
                          max={100}
                          value={settingsDraft.pass_score}
                          onChange={(e) =>
                            setSettingsDraft((s) => ({
                              ...s,
                              pass_score: Math.max(1, Math.min(100, parseInt(e.target.value, 10) || 80)),
                            }))
                          }
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-muted-foreground">{t('quiz.timeLeft')} (мин, пусто = без лимита)</span>
                        <Input
                          type="number"
                          min={1}
                          value={settingsDraft.time_limit}
                          onChange={(e) =>
                            setSettingsDraft((s) => ({ ...s, time_limit: e.target.value }))
                          }
                          placeholder="∞"
                        />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-muted-foreground">Попыток</span>
                        <Input
                          type="number"
                          min={1}
                          max={99}
                          value={settingsDraft.attempt_limit}
                          onChange={(e) =>
                            setSettingsDraft((s) => ({
                              ...s,
                              attempt_limit: Math.max(1, parseInt(e.target.value, 10) || 1),
                            }))
                          }
                        />
                      </label>
                      <div className="flex justify-end gap-2 md:col-span-3">
                        <Button variant="outline" size="sm" onClick={() => setEditingSettings(false)} disabled={savingSettings}>
                          {t('common.cancel')}
                        </Button>
                        <Button size="sm" onClick={handleSaveQuizSettings} disabled={savingSettings}>
                          {savingSettings ? t('common.saving') : t('common.save')}
                        </Button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="rounded-md border border-border/70 bg-muted/30 px-4 py-3">
                        <div className="text-xs text-muted-foreground">{t('quiz.passScore')}</div>
                        <div className="mt-1 text-lg font-semibold tabular-nums">{selectedQuiz.pass_score}%</div>
                      </div>
                      <div className="rounded-md border border-border/70 bg-muted/30 px-4 py-3">
                        <div className="text-xs text-muted-foreground">{t('quiz.timeLeft')}</div>
                        <div className="mt-1 text-lg font-semibold tabular-nums">{selectedQuiz.time_limit ? `${selectedQuiz.time_limit} мин` : '∞'}</div>
                      </div>
                      <div className="rounded-md border border-border/70 bg-muted/30 px-4 py-3">
                        <div className="text-xs text-muted-foreground">Попыток</div>
                        <div className="mt-1 text-lg font-semibold tabular-nums">{selectedQuiz.attempt_limit}</div>
                      </div>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Questions */}
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h4 className="text-base font-semibold text-foreground">Вопросы</h4>
                <Button size="sm" className="h-9" onClick={() => setShowAddQuestion(!showAddQuestion)}>
                  + {t('common.create')} вопрос
                </Button>
              </div>

              {showAddQuestion && (
                <Card className="border-primary/40">
                  <CardContent className="p-4 space-y-3">
                    <Input
                      placeholder="Текст вопроса"
                      value={newQuestion.text}
                      onChange={(e) => setNewQuestion((p) => ({ ...p, text: e.target.value }))}
                    />
                    <div className="grid grid-cols-3 gap-3">
                      <select
                        value={newQuestion.type}
                        onChange={(e) => setNewQuestion((p) => ({ ...p, type: e.target.value }))}
                        className="border rounded px-2 py-1 text-sm"
                      >
                        <option value="MCQ">MCQ (выбор)</option>
                        <option value="true_false">True/False</option>
                        <option value="matching">Matching</option>
                      </select>
                      <Input
                        type="number"
                        placeholder="Баллы"
                        value={newQuestion.points}
                        onChange={(e) => setNewQuestion((p) => ({ ...p, points: parseInt(e.target.value) || 1 }))}
                      />
                    </div>
                    <Input
                      placeholder="Объяснение (опционально)"
                      value={newQuestion.explanation}
                      onChange={(e) => setNewQuestion((p) => ({ ...p, explanation: e.target.value }))}
                    />
                    <div className="space-y-2">
                      <p className="text-sm font-medium">Варианты ответов:</p>
                      {newChoices.map((c, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <input
                            type="radio"
                            name="correct-choice"
                            checked={c.is_correct}
                            onChange={() => {
                              setNewChoices((prev) => prev.map((ch, j) => ({ ...ch, is_correct: j === i })));
                            }}
                          />
                          <Input
                            placeholder={`Вариант ${i + 1}`}
                            value={c.text}
                            onChange={(e) => {
                              setNewChoices((prev) => prev.map((ch, j) => j === i ? { ...ch, text: e.target.value } : ch));
                            }}
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Button onClick={handleAddQuestion}>{t('common.create')}</Button>
                      <Button variant="outline" onClick={() => setShowAddQuestion(false)}>{t('common.cancel')}</Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {selectedQuiz.questions.map((q, i) => (
                <Card key={q.id} className="border-border/70 shadow-none">
                  <CardContent className="p-0">
                    <div className="grid grid-cols-[44px_minmax(0,1fr)_auto] gap-4 px-4 py-4">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-muted text-sm font-medium tabular-nums text-muted-foreground">
                        {i + 1}
                      </div>
                      <div className="min-w-0">
                        <div className="mb-3 flex flex-wrap items-start gap-2">
                          <span className="min-w-0 flex-1 text-base font-medium leading-6 text-foreground">{q.text}</span>
                          <Badge variant="secondary" className="bg-primary/10 text-primary">{q.points} {t('quiz.points')}</Badge>
                          <Badge variant="outline" className="border-border bg-card text-muted-foreground">{q.type}</Badge>
                        </div>
                        <div className="space-y-2">
                          {q.choices.map((c) => (
                            <div key={c.id} className={`flex items-start gap-2 text-sm leading-5 ${c.is_correct ? 'font-medium text-success' : 'text-muted-foreground'}`}>
                              {c.is_correct ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0" />}
                              <span className="min-w-0 break-words">{c.text}</span>
                            </div>
                          ))}
                        </div>
                        {q.explanation && (
                          <div className="mt-3 flex items-start gap-2 rounded-md bg-primary/5 px-3 py-2 text-xs leading-5 text-primary">
                            <Lightbulb className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>{q.explanation}</span>
                          </div>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => handleDeleteQuestion(q.id)}
                      >
                        {t('common.delete')}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* Assignments — назначить тест сотрудникам.
                Это часть рабочего цикла методолога: написал вопросы →
                назначил кому надо → видно кто прошёл, кто нет.
                refreshKey === quiz.id гарантирует, что при выборе другого
                теста панель перезагружает данные. */}
            <div id="assignments" className="scroll-mt-6 pt-2">
              <QuizAssignPanel quizId={selectedQuiz.id} refreshKey={selectedQuiz.id} />
            </div>
          </div>
        ) : (
          <Card className="border-border/70 shadow-none">
            <CardContent className="p-10 text-center text-muted-foreground">
              Загрузите тест по ID или создайте новый
            </CardContent>
          </Card>
        )}
      </div>
{dialog}
    </div>
  );
}
