'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, Button, Badge, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { CheckCircle2, Circle, Lightbulb, ChevronRight, ChevronDown } from 'lucide-react';

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
  questions: Question[];
}

// Course preview types — matches backend GET /v1/courses/{id}/preview.
// We use this endpoint for the cascade selector instead of inventing a new
// tree endpoint; it already returns modules → lessons with has_quiz flags,
// which is exactly what we need to (a) pick a lesson for a new quiz and
// (b) group existing quizzes in the list.
interface PreviewLesson {
  id: string;
  title: string;
  order_index: number;
  has_quiz: boolean;
  quiz_id: string | null;
  quiz_title: string | null;
  quiz_question_count: number;
}

interface PreviewModule {
  id: string;
  title: string;
  order_index: number;
  lessons: PreviewLesson[];
}

interface CoursePreview {
  id: string;
  title: string;
  modules_count: number;
  lessons_count: number;
  quizzes_count: number;
  modules: PreviewModule[];
}

interface CourseLite {
  id: string;
  title: string;
}

export default function QuizzesAdminPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedQuiz, setSelectedQuiz] = useState<Quiz | null>(null);
  const [editing, setEditing] = useState(false);
  // Cascade selector state — Course → Module → Lesson. Replaces the old
  // free-form "Lesson ID (UUID)" input that forced methodologists to
  // look up UUIDs in the database, which was a usability dead end.
  const [courses, setCourses] = useState<CourseLite[]>([]);
  const [previews, setPreviews] = useState<Record<string, CoursePreview>>({});
  const [loadingPreviews, setLoadingPreviews] = useState<Record<string, boolean>>({});
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
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchQuizzes = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/quizzes`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setQuizzes(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  const fetchCourses = useCallback(async () => {
    if (!token) return;
    const res = await fetch(`${API_URL}/v1/courses`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) setCourses(await res.json());
  }, [token, API_URL]);

  // Lazy-load preview for a course — only when the user expands it in the
  // cascade selector. Prevents N+1 fetches when there are many courses.
  const fetchPreview = useCallback(
    async (courseId: string) => {
      if (!token || previews[courseId] || loadingPreviews[courseId]) return;
      setLoadingPreviews((p) => ({ ...p, [courseId]: true }));
      try {
        const res = await fetch(
          `${API_URL}/v1/courses/${courseId}/preview?max_chars=80`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (res.ok) {
          const data: CoursePreview = await res.json();
          setPreviews((p) => ({ ...p, [courseId]: data }));
        }
      } finally {
        setLoadingPreviews((p) => ({ ...p, [courseId]: false }));
      }
    },
    [token, API_URL, previews, loadingPreviews]
  );

  useEffect(() => { fetchQuizzes(); }, [fetchQuizzes]);
  useEffect(() => { fetchCourses(); }, [fetchCourses]);

  // Index quiz → lesson → module → course for grouping in the list.
  // Without this we only have lesson_id which is useless on its own.
  const quizIndex = useMemo(() => {
    const byQuizId: Record<string, { lesson?: PreviewLesson; module?: PreviewModule; course?: CourseLite }> = {};
    for (const course of courses) {
      const prev = previews[course.id];
      if (!prev) continue;
      for (const m of prev.modules) {
        for (const l of m.lessons) {
          if (l.quiz_id) {
            byQuizId[l.quiz_id] = { lesson: l, module: m, course };
          }
        }
      }
    }
    return byQuizId;
  }, [courses, previews]);

  // Group quizzes by Course → Module → Lesson for the list panel.
  // Quizzes whose lesson we can't locate (e.g. lesson deleted, preview
  // not yet loaded) fall into a single "Без привязки" bucket so they
  // don't disappear from the UI.
  const grouped = useMemo(() => {
    const buckets: Array<{
      course: CourseLite;
      modules: Array<{
        module: PreviewModule;
        lessons: Array<{ lesson: PreviewLesson | null; quiz: Quiz }>;
      }>;
    }> = [];
    const orphan: Quiz[] = [];

    for (const course of courses) {
      const prev = previews[course.id];
      if (!prev) continue;
      const courseBucket = { course, modules: [] as Array<{ module: PreviewModule; lessons: Array<{ lesson: PreviewLesson | null; quiz: Quiz }> }> };
      for (const m of prev.modules) {
        const moduleBucket = { module: m, lessons: [] as Array<{ lesson: PreviewLesson | null; quiz: Quiz }> };
        for (const l of m.lessons) {
          if (l.has_quiz && l.quiz_id) {
            const q = quizzes.find((qz) => qz.id === l.quiz_id);
            if (q) moduleBucket.lessons.push({ lesson: l, quiz: q });
          }
        }
        if (moduleBucket.lessons.length > 0) courseBucket.modules.push(moduleBucket);
      }
      if (courseBucket.modules.length > 0) buckets.push(courseBucket);
    }

    for (const q of quizzes) {
      if (!quizIndex[q.id]) orphan.push(q);
    }

    return { buckets, orphan };
  }, [courses, previews, quizzes, quizIndex]);

  const handleCreateQuiz = async () => {
    if (!token || !newQuiz.lesson_id || !newQuiz.title) return;
    const res = await fetch(`${API_URL}/v1/quizzes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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
      setQuizzes((prev) => [...prev, quiz]);
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
      // Refresh the preview for the chosen course so the new quiz shows up
      // in the grouped list immediately, without waiting for a full reload.
      if (newQuiz.course_id) {
        setPreviews((p) => {
          const next = { ...p };
          delete next[newQuiz.course_id];
          return next;
        });
        fetchPreview(newQuiz.course_id);
      }
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
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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
      await fetchQuizzes();
      if (newQuiz.course_id) {
        setPreviews((p) => {
          const next = { ...p };
          delete next[newQuiz.course_id];
          return next;
        });
        fetchPreview(newQuiz.course_id);
      }
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
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
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
      headers: { Authorization: `Bearer ${token}` },
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
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      setQuizzes((prev) => prev.filter((q) => q.id !== quizId));
      setSelectedQuiz(null);
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
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const updated = await res.json();
      // Patch both the list and the selected detail so the UI updates
      // without a full refetch.
      setQuizzes((prev) => prev.map((q) => (q.id === updated.id ? updated : q)));
      setSelectedQuiz(updated);
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          {/* Page header renamed on 2026-06-27 from "Тест — Админ" to
              "Конструктор тестов" — the old label sounded like an admin
              operations panel, but this is actually a content-construction
              page where the methodologist authors quiz questions. The
              subtitle clarifies the workflow: pick a lesson → write/AI the
              questions → save. */}
          <h1 className="text-2xl font-bold">Конструктор тестов</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Создание и редактирование тестов. Выберите урок → добавьте вопросы вручную или сгенерируйте черновик из контента урока с помощью AI.
          </p>
        </div>
        <Button onClick={() => setShowCreateQuiz(!showCreateQuiz)}>
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
                lazy-load GET /v1/courses/{id}/preview to enumerate
                lessons in the chosen course, marking ones that already
                have a quiz so we don't accidentally create a second
                quiz for the same lesson. */}
            <div className="grid md:grid-cols-3 gap-2">
              <div>
                <label className="text-sm text-muted-foreground">Курс</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={newQuiz.course_id}
                  onChange={(e) => {
                    const cid = e.target.value;
                    setNewQuiz((p) => ({ ...p, course_id: cid, module_id: '', lesson_id: '' }));
                    fetchPreview(cid);
                  }}
                >
                  <option value="">— выберите курс —</option>
                  {courses.map((c) => (
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
                  disabled={!newQuiz.course_id || loadingPreviews[newQuiz.course_id]}
                >
                  <option value="">— выберите модуль —</option>
                  {(previews[newQuiz.course_id]?.modules ?? []).map((m) => (
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
                  {(previews[newQuiz.course_id]?.modules ?? [])
                    .find((m) => m.id === newQuiz.module_id)
                    ?.lessons.map((l) => (
                      <option key={l.id} value={l.id} disabled={l.has_quiz}>
                        {l.title}{l.has_quiz ? ' (уже есть тест)' : ''}
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

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Quiz list — grouped by Course → Module → Lesson.
            Replaces the flat list + dev-only "Load quiz by ID" panel.
            Each row shows the quiz title and a count badge so the
            methodologist can scan it without expanding every group. */}
        <Card>
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Тесты</h3>
              <Badge variant="secondary">{quizzes.length}</Badge>
            </div>
            {loading ? (
              <p className="text-sm text-muted-foreground">Загрузка…</p>
            ) : grouped.buckets.length === 0 && grouped.orphan.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Тестов пока нет. Нажмите «Создать тест» выше.
              </p>
            ) : (
              <div className="space-y-1 max-h-[28rem] overflow-y-auto">
                {grouped.buckets.map(({ course, modules }) => {
                  const isOpen = openCourses[course.id] ?? true;
                  return (
                    <div key={course.id} className="rounded border border-border/50">
                      <button
                        type="button"
                        className="w-full flex items-center gap-1 px-2 py-1.5 text-left text-sm font-medium hover:bg-muted/50"
                        onClick={() => setOpenCourses((p) => ({ ...p, [course.id]: !isOpen }))}
                      >
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <span className="flex-1 truncate">{course.title}</span>
                        <Badge variant="outline">
                          {modules.reduce((acc, mb) => acc + mb.lessons.length, 0)}
                        </Badge>
                      </button>
                      {isOpen && (
                        <div className="pl-5 pr-2 pb-2 space-y-2">
                          {modules.map(({ module, lessons }) => (
                            <div key={module.id}>
                              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide px-1 py-1">
                                {module.title}
                              </div>
                              {lessons.map(({ lesson, quiz }) => (
                                <div
                                  key={quiz.id}
                                  className={`p-2 rounded cursor-pointer text-sm ${
                                    selectedQuiz?.id === quiz.id ? 'bg-primary/10' : 'hover:bg-muted'
                                  }`}
                                  onClick={() => setSelectedQuiz(quiz)}
                                >
                                  <div className="flex items-center gap-2">
                                    <Circle size={10} className="shrink-0" />
                                    <span className="flex-1 truncate">{lesson?.title ?? quiz.title}</span>
                                    <Badge className="ml-2">{quiz.questions.length}</Badge>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
                {grouped.orphan.length > 0 && (
                  <div className="rounded border border-dashed border-border/50 mt-2">
                    <div className="px-2 py-1.5 text-xs uppercase tracking-wide text-muted-foreground">
                      Без привязки
                    </div>
                    {grouped.orphan.map((q) => (
                      <div
                        key={q.id}
                        className={`p-2 rounded cursor-pointer text-sm ${
                          selectedQuiz?.id === q.id ? 'bg-primary/10' : 'hover:bg-muted'
                        }`}
                        onClick={() => setSelectedQuiz(q)}
                      >
                        <div className="flex items-center gap-2">
                          <Circle size={10} className="shrink-0" />
                          <span className="flex-1 truncate">{q.title}</span>
                          <Badge className="ml-2">{q.questions.length}</Badge>
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
          <div className="lg:col-span-2 space-y-4">
            <Card>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-lg">{selectedQuiz.title}</h3>
                  <div className="flex gap-2">
                    {!editingSettings && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => startEditSettings(selectedQuiz)}
                      >
                        Изменить параметры
                      </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => handleDeleteQuiz(selectedQuiz.id)}>
                      {t('common.delete')}
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
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
                      <div className="md:col-span-3 flex gap-2 justify-end">
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
                      <div>{t('quiz.passScore')}: <strong>{selectedQuiz.pass_score}%</strong></div>
                      <div>{t('quiz.timeLeft')}: <strong>{selectedQuiz.time_limit ? `${selectedQuiz.time_limit} мин` : '∞'}</strong></div>
                      <div>Попыток: <strong>{selectedQuiz.attempt_limit}</strong></div>
                    </>
                  )}
                </div>
                <div className="text-sm text-muted-foreground">
                  {selectedQuiz.questions.length} вопросов · {selectedQuiz.questions.reduce((a, q) => a + q.points, 0)} баллов
                </div>
              </CardContent>
            </Card>

            {/* Questions */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-semibold">Вопросы</h4>
                <Button size="sm" onClick={() => setShowAddQuestion(!showAddQuestion)}>
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
                <Card key={q.id}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="outline">{i + 1}</Badge>
                          <span className="font-medium">{q.text}</span>
                          <Badge>{q.points} {t('quiz.points')}</Badge>
                          <Badge variant="outline">{q.type}</Badge>
                        </div>
                        <div className="ml-8 space-y-1">
                          {q.choices.map((c) => (
                            <div key={c.id} className={`flex items-center gap-1 text-sm ${c.is_correct ? 'text-success font-medium' : 'text-muted-foreground'}`}>
                              {c.is_correct ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />} {c.text}
                            </div>
                          ))}
                        </div>
                        {q.explanation && (
                          <div className="ml-8 mt-2 flex items-center gap-1 text-xs text-primary">
                            <Lightbulb className="w-4 h-4" /> {q.explanation}
                          </div>
                        )}
                      </div>
                      <Button variant="destructive" size="sm" onClick={() => handleDeleteQuestion(q.id)}>
                        {t('common.delete')}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ) : (
          <Card className="lg:col-span-2">
            <CardContent className="p-8 text-center text-muted-foreground">
              Загрузите тест по ID или создайте новый
            </CardContent>
          </Card>
        )}
      </div>
{dialog}
    </div>
  );
}
