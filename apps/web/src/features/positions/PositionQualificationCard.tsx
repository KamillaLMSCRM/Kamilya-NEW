"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  BookOpenCheck,
  BriefcaseBusiness,
  ClipboardCheck,
  FileClock,
  FileText,
  History,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button } from "@/components/ui";
import { toast } from "@/components/ui/Toast";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";

import {
  getQualificationCard,
  getQualificationHistory,
  replaceMandatoryTraining,
  replacePositionCompetencies,
  restoreQualificationVersion,
  updateQualificationProfile,
} from "./qualification-api";
import type {
  CompetencyCatalogItem,
  CourseCatalogItem,
  PositionQualificationCardData,
  QualificationHistoryItem,
  QualificationTab,
  QuizQuestionDraft,
} from "./qualification-types";

const TABS: Array<{
  id: QualificationTab;
  label: string;
  icon: typeof BriefcaseBusiness;
}> = [
  { id: "profile", label: "Профиль", icon: BriefcaseBusiness },
  { id: "instruction", label: "Должностная инструкция", icon: FileText },
  { id: "competencies", label: "Компетенции", icon: ClipboardCheck },
  { id: "training", label: "Обязательное обучение", icon: BookOpenCheck },
  // The legacy position quiz editor stays hidden until it has a real
  // assignment, learner-delivery and reporting flow.
  { id: "history", label: "История версий", icon: History },
];

const VALID_TABS = new Set<QualificationTab>(TABS.map((tab) => tab.id));

function messageFromError(error: unknown, fallback: string) {
  const data = (
    error as {
      response?: {
        data?: {
          detail?: unknown;
          details?: unknown;
          message?: unknown;
        };
      };
    }
  )?.response?.data;
  const detail = data?.detail ?? data?.details;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail && detail.message) {
    return String(detail.message);
  }
  if (typeof data?.message === "string") return data.message;
  return fallback;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Нет данных";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    ready: "Готов",
    partial: "Частично готов",
    processing: "Обрабатывается",
    failed: "Ошибка",
    published: "Опубликован",
    draft: "Черновик",
    archived: "В архиве",
  };
  return labels[status] ?? status;
}

function createEmptyQuestion(): QuizQuestionDraft {
  return {
    text: "",
    type: "MCQ",
    explanation: "",
    choices: [
      { text: "", is_correct: true },
      { text: "", is_correct: false },
    ],
  };
}

interface Props {
  positionId: string;
}

export function PositionQualificationCard({ positionId }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const uploadRef = useRef<HTMLInputElement>(null);
  const { confirm, dialog } = useConfirm();

  const requestedTab = searchParams?.get("tab") as QualificationTab | null;
  const activeTab = requestedTab && VALID_TABS.has(requestedTab) ? requestedTab : "profile";

  const [card, setCard] = useState<PositionQualificationCardData | null>(null);
  const [competencyCatalog, setCompetencyCatalog] = useState<CompetencyCatalogItem[]>([]);
  const [courseCatalog, setCourseCatalog] = useState<CourseCatalogItem[]>([]);
  const [history, setHistory] = useState<QualificationHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const [profileDraft, setProfileDraft] = useState({
    name: "",
    department: "",
    level: "",
    responsibilities: "",
    requirements: "",
    change_reason: "",
  });
  const [competencyDraft, setCompetencyDraft] = useState<Record<string, number>>({});
  const [trainingDraft, setTrainingDraft] = useState<Record<string, boolean>>({});
  const [quizDraft, setQuizDraft] = useState({
    title: "",
    pass_score: 80,
    time_limit: "" as number | "",
    is_active: true,
    questions: [] as QuizQuestionDraft[],
  });

  const syncDrafts = useCallback((next: PositionQualificationCardData) => {
    setProfileDraft({
      name: next.profile.name,
      department: next.profile.department ?? "",
      level: next.profile.level ?? "",
      responsibilities: next.profile.responsibilities ?? "",
      requirements: next.profile.requirements ?? "",
      change_reason: "",
    });
    setCompetencyDraft(Object.fromEntries(next.competencies.map((item) => [item.id, item.required_level])));
    setTrainingDraft(Object.fromEntries(next.training.position_courses.map((item) => [item.course_id, item.required])));
    setQuizDraft({
      title: next.onboarding_quiz?.title ?? `Onboarding: ${next.profile.name}`,
      pass_score: next.onboarding_quiz?.pass_score ?? 80,
      time_limit: next.onboarding_quiz?.time_limit ?? "",
      is_active: next.onboarding_quiz?.is_active ?? true,
      questions: next.onboarding_quiz?.questions ?? [],
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setCatalogError(null);
    try {
      const [cardResult, competenciesResult, coursesResult] = await Promise.allSettled([
        getQualificationCard(positionId),
        api.get<CompetencyCatalogItem[]>("/v1/competencies"),
        api.get("/v1/courses?per_page=100"),
      ]);
      if (cardResult.status === "rejected") throw cardResult.reason;
      const nextCard = cardResult.value;
      const competencies = competenciesResult.status === "fulfilled" ? competenciesResult.value.data : [];
      const courses =
        coursesResult.status === "fulfilled" ? (coursesResult.value.data?.items ?? coursesResult.value.data ?? []) : [];
      if (competenciesResult.status === "rejected" || coursesResult.status === "rejected") {
        setCatalogError("Карточка загружена, но справочники компетенций или курсов временно недоступны.");
      }
      setCard(nextCard);
      setCompetencyCatalog(competencies);
      setCourseCatalog(courses);
      syncDrafts(nextCard);
    } catch (loadError) {
      setError(messageFromError(loadError, "Не удалось загрузить карточку должности. Повторите попытку."));
    } finally {
      setLoading(false);
    }
  }, [positionId, syncDrafts]);

  useEffect(() => {
    load();
  }, [load]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await getQualificationHistory(positionId));
    } catch (historyError) {
      toast.error(messageFromError(historyError, "Не удалось загрузить историю версий"));
    } finally {
      setHistoryLoading(false);
    }
  }, [positionId]);

  useEffect(() => {
    if (activeTab === "history") loadHistory();
  }, [activeTab, loadHistory]);

  const chooseTab = (tab: QualificationTab) => {
    const params = new URLSearchParams(searchParams?.toString());
    params.set("tab", tab);
    router.replace(`/positions/${positionId}?${params.toString()}`, {
      scroll: false,
    });
  };

  const applyCard = (next: PositionQualificationCardData) => {
    setCard(next);
    syncDrafts(next);
  };

  const saveProfile = async () => {
    if (!profileDraft.name.trim()) {
      toast.error("Укажите название должности");
      return;
    }
    setSaving("profile");
    try {
      const next = await updateQualificationProfile(positionId, {
        name: profileDraft.name.trim(),
        department: profileDraft.department.trim(),
        level: profileDraft.level.trim(),
        responsibilities: profileDraft.responsibilities.trim(),
        requirements: profileDraft.requirements.trim(),
        change_reason: profileDraft.change_reason.trim() || undefined,
      });
      applyCard(next);
      toast.success("Профиль должности сохранён");
    } catch (saveError) {
      toast.error(messageFromError(saveError, "Не удалось сохранить профиль"));
    } finally {
      setSaving(null);
    }
  };

  const saveCompetencies = async () => {
    setSaving("competencies");
    try {
      const next = await replacePositionCompetencies(
        positionId,
        Object.entries(competencyDraft).map(([competency_id, required_level]) => ({
          competency_id,
          required_level,
        })),
      );
      applyCard(next);
      toast.success("Требования к компетенциям сохранены");
    } catch (saveError) {
      toast.error(messageFromError(saveError, "Не удалось сохранить компетенции"));
    } finally {
      setSaving(null);
    }
  };

  const saveTraining = async () => {
    setSaving("training");
    try {
      const next = await replaceMandatoryTraining(
        positionId,
        Object.entries(trainingDraft).map(([course_id, required]) => ({
          course_id,
          required,
        })),
      );
      applyCard(next);
      toast.success("Правила обязательного обучения сохранены");
    } catch (saveError) {
      toast.error(messageFromError(saveError, "Не удалось сохранить правила обучения"));
    } finally {
      setSaving(null);
    }
  };

  const uploadInstruction = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setSaving("instruction");
    try {
      const form = new FormData();
      form.append("file", file);
      await api.post(`/v1/positions/${positionId}/instruction`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await load();
      toast.success("Новая версия инструкции загружена");
    } catch (uploadError) {
      toast.error(messageFromError(uploadError, "Не удалось загрузить инструкцию. Проверьте формат файла."));
    } finally {
      event.target.value = "";
      setSaving(null);
    }
  };

  const downloadInstruction = async () => {
    if (!card?.instruction) return;
    setSaving("download");
    try {
      const response = await api.get(`/v1/documents/${card.instruction.document_id}/download`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = card.instruction.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      toast.error(messageFromError(downloadError, "Не удалось скачать инструкцию"));
    } finally {
      setSaving(null);
    }
  };

  const generateQuiz = async () => {
    setSaving("quiz-generate");
    try {
      const response = await api.post(`/v1/positions/${positionId}/suggest-onboarding-quiz`);
      setQuizDraft((current) => ({
        ...current,
        title: response.data.title,
        questions: response.data.questions,
      }));
      toast.success("Черновик теста создан. Проверьте вопросы перед сохранением.");
    } catch (quizError) {
      toast.error(messageFromError(quizError, "Не удалось создать черновик теста"));
    } finally {
      setSaving(null);
    }
  };

  const saveQuiz = async () => {
    if (!quizDraft.title.trim() || quizDraft.questions.length === 0) {
      toast.error("Добавьте название и хотя бы 1 вопрос");
      return;
    }
    const invalidQuestionIndex = quizDraft.questions.findIndex(
      (question) =>
        !question.text.trim() ||
        question.choices.length < 2 ||
        question.choices.some((choice) => !choice.text.trim()) ||
        question.choices.filter((choice) => choice.is_correct).length !== 1,
    );
    if (invalidQuestionIndex >= 0) {
      toast.error(
        `Проверьте вопрос ${invalidQuestionIndex + 1}: нужен текст, минимум 2 варианта и ровно 1 правильный ответ`,
      );
      return;
    }
    setSaving("quiz");
    try {
      await api.post(`/v1/positions/${positionId}/onboarding-quiz`, {
        title: quizDraft.title.trim(),
        pass_score: quizDraft.pass_score,
        time_limit: quizDraft.time_limit || null,
        questions: quizDraft.questions,
        is_active: quizDraft.is_active,
      });
      await load();
      toast.success("Onboarding-тест сохранён");
    } catch (quizError) {
      toast.error(messageFromError(quizError, "Не удалось сохранить тест"));
    } finally {
      setSaving(null);
    }
  };

  const deleteQuiz = async () => {
    const accepted = await confirm({
      title: "Удалить onboarding-тест?",
      message: "Вопросы будут удалены из карточки должности.",
      variant: "danger",
      confirmLabel: "Удалить тест",
    });
    if (!accepted) return;
    setSaving("quiz-delete");
    try {
      await api.delete(`/v1/positions/${positionId}/onboarding-quiz`);
      await load();
      toast.success("Onboarding-тест удалён");
    } catch (quizError) {
      toast.error(messageFromError(quizError, "Не удалось удалить тест"));
    } finally {
      setSaving(null);
    }
  };

  const restoreVersion = async (item: QualificationHistoryItem) => {
    const accepted = await confirm({
      title: `Восстановить версию ${item.version_no}?`,
      message:
        "Текущая конфигурация останется в истории как новая версия, после чего будет восстановлен выбранный снимок.",
      variant: "warning",
      confirmLabel: "Восстановить",
    });
    if (!accepted) return;
    setSaving(`restore-${item.id}`);
    try {
      const next = await restoreQualificationVersion(positionId, item.id, `Восстановление версии ${item.version_no}`);
      applyCard(next);
      await loadHistory();
      toast.success(`Версия ${item.version_no} восстановлена`);
    } catch (restoreError) {
      toast.error(
        messageFromError(restoreError, "Не удалось восстановить версию. Проверьте доступность связанных объектов."),
      );
    } finally {
      setSaving(null);
    }
  };

  const selectedCourseCount = Object.keys(trainingDraft).length;
  const publishedEffectiveCount = useMemo(
    () => card?.training.effective_courses.filter((course) => course.status === "published").length ?? 0,
    [card],
  );

  if (loading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center" aria-live="polite">
        <RefreshCw className="h-7 w-7 animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />
        <span className="sr-only">Загрузка карточки должности…</span>
      </div>
    );
  }

  if (error || !card) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="text-xl font-semibold text-foreground">Карточка должности недоступна</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error ?? "Должность не найдена или у вас нет доступа."}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button type="button" onClick={load}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            Повторить
          </Button>
          <Link
            href="/positions"
            className="inline-flex h-10 items-center rounded-md border border-input px-4 text-sm font-medium text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Вернуться к должностям
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1280px] space-y-6 pb-10">
      <header className="space-y-4">
        <Link
          href="/positions"
          className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Все должности
        </Link>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-2xl font-bold text-foreground sm:text-3xl">{card.profile.name}</h1>
              {card.profile.level ? <Badge variant="secondary">{card.profile.level}</Badge> : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{card.profile.department || "Отдел не указан"}</p>
          </div>

          <dl className="grid min-w-0 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:min-w-[520px]">
            <div>
              <dt className="text-xs text-muted-foreground">Сотрудников</dt>
              <dd className="mt-1 flex items-center gap-1.5 font-semibold tabular-nums">
                <Users className="h-4 w-4 text-primary" aria-hidden="true" />
                {card.employees.active_count}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Компетенций</dt>
              <dd className="mt-1 font-semibold tabular-nums">{card.competencies.length}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Курсов</dt>
              <dd className="mt-1 font-semibold tabular-nums">
                {publishedEffectiveCount}/{card.training.effective_courses.length}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Версия</dt>
              <dd className="mt-1 font-semibold tabular-nums">{card.latest_version ?? "—"}</dd>
            </div>
          </dl>
        </div>
      </header>

      <nav aria-label="Разделы карточки должности" className="-mx-1 overflow-x-auto px-1 pb-1">
        <div className="flex min-w-max gap-1 border-b border-border">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                aria-current={selected ? "page" : undefined}
                onClick={() => chooseTab(tab.id)}
                className={`inline-flex min-h-11 items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  selected
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </nav>

      {activeTab === "profile" ? (
        <section aria-labelledby="profile-heading" className="space-y-5">
          <div>
            <h2 id="profile-heading" className="text-xl font-semibold">
              Профиль должности
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Базовые требования используются в должностной инструкции и AI-рекомендациях.
            </p>
          </div>
          <div className="grid gap-5 rounded-lg border border-border bg-card p-5 lg:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-sm font-medium">Название</span>
              <input
                name="position_name"
                autoComplete="off"
                value={profileDraft.name}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Отдел</span>
                <input
                  name="position_department"
                  autoComplete="off"
                  value={profileDraft.department}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      department: event.target.value,
                    }))
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Уровень</span>
                <input
                  name="position_level"
                  autoComplete="off"
                  value={profileDraft.level}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      level: event.target.value,
                    }))
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
            </div>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">Обязанности</span>
              <textarea
                name="position_responsibilities"
                autoComplete="off"
                rows={8}
                value={profileDraft.responsibilities}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    responsibilities: event.target.value,
                  }))
                }
                className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">Требования</span>
              <textarea
                name="position_requirements"
                autoComplete="off"
                rows={8}
                value={profileDraft.requirements}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    requirements: event.target.value,
                  }))
                }
                className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <label className="space-y-1.5 lg:col-span-2">
              <span className="text-sm font-medium">
                Причина изменения <span className="font-normal text-muted-foreground">(необязательно)</span>
              </span>
              <input
                name="profile_change_reason"
                autoComplete="off"
                placeholder="Например: актуализация после изменения процесса…"
                value={profileDraft.change_reason}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    change_reason: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <div className="flex justify-end lg:col-span-2">
              <Button type="button" onClick={saveProfile} disabled={saving === "profile"}>
                <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                {saving === "profile" ? "Сохранение…" : "Сохранить профиль"}
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "instruction" ? (
        <section aria-labelledby="instruction-heading" className="space-y-5">
          <div>
            <h2 id="instruction-heading" className="text-xl font-semibold">
              Должностная инструкция
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Исходник хранится в единой библиотеке документов и связан с этой должностью.
            </p>
          </div>
          <input
            ref={uploadRef}
            type="file"
            accept=".pdf,.doc,.docx,.txt,.md"
            className="hidden"
            onChange={uploadInstruction}
          />
          {card.instruction ? (
            <div className="rounded-lg border border-border bg-card p-5">
              <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <FileText className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
                  <div className="min-w-0">
                    <h3 className="break-words font-semibold">{card.instruction.filename}</h3>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge variant="secondary">Версия {card.instruction.version}</Badge>
                      <Badge variant={card.instruction.index_status === "failed" ? "destructive" : "secondary"}>
                        {statusLabel(card.instruction.index_status)}
                      </Badge>
                    </div>
                    <p className="mt-3 text-sm text-muted-foreground">
                      Обновлено: {formatDate(card.instruction.updated_at)}
                    </p>
                    {card.instruction.index_error_code ? (
                      <p className="mt-2 text-sm text-destructive">
                        Индексация завершилась ошибкой. Загрузите исправленную версию документа.
                      </p>
                    ) : null}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={downloadInstruction}
                    disabled={saving === "download"}
                  >
                    <FileText className="mr-2 h-4 w-4" aria-hidden="true" />
                    Скачать
                  </Button>
                  <Button type="button" onClick={() => uploadRef.current?.click()} disabled={saving === "instruction"}>
                    <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
                    {saving === "instruction" ? "Загрузка…" : "Загрузить новую версию"}
                  </Button>
                </div>
              </div>
              <div className="mt-5 border-t border-border pt-4">
                <Link
                  href={`/documents?search=${encodeURIComponent(card.instruction.filename)}`}
                  className="text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Открыть источник в библиотеке документов
                </Link>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border px-5 py-12 text-center">
              <FileText className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <h3 className="mt-3 font-semibold">Инструкция не загружена</h3>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                Загрузите утверждённый документ. Он будет проиндексирован и доступен для генерации курса по должности.
              </p>
              <Button
                type="button"
                className="mt-5"
                onClick={() => uploadRef.current?.click()}
                disabled={saving === "instruction"}
              >
                <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
                {saving === "instruction" ? "Загрузка…" : "Загрузить документ"}
              </Button>
            </div>
          )}
        </section>
      ) : null}

      {activeTab === "competencies" ? (
        <section aria-labelledby="competencies-heading" className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="competencies-heading" className="text-xl font-semibold">
                Компетенции должности
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Выберите обязательные компетенции и ожидаемый уровень от 1 до 5.
              </p>
            </div>
            <Link
              href="/competencies"
              className="text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Открыть справочник компетенций
            </Link>
          </div>
          {catalogError ? (
            <div
              role="alert"
              className="flex flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between"
            >
              <span>{catalogError}</span>
              <Button type="button" variant="outline" onClick={load}>
                <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                Повторить
              </Button>
            </div>
          ) : null}
          {competencyCatalog.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
              <p className="text-sm text-muted-foreground">В справочнике пока нет компетенций.</p>
              <Link
                href="/competencies"
                className="mt-4 inline-flex h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Создать компетенцию
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {competencyCatalog.map((item) => {
                const selected = item.id in competencyDraft;
                return (
                  <div
                    key={item.id}
                    className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center"
                  >
                    <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={(event) =>
                          setCompetencyDraft((current) => {
                            const next = { ...current };
                            if (event.target.checked) next[item.id] = 1;
                            else delete next[item.id];
                            return next;
                          })
                        }
                        className="mt-1 h-4 w-4 rounded border-input text-primary focus-visible:ring-2 focus-visible:ring-ring"
                      />
                      <span className="min-w-0">
                        <span className="block break-words font-medium">{item.name}</span>
                        {item.description ? (
                          <span className="mt-1 block text-sm text-muted-foreground">{item.description}</span>
                        ) : null}
                      </span>
                    </label>
                    {selected ? (
                      <label className="flex items-center gap-2 text-sm">
                        <span className="text-muted-foreground">Требуемый уровень</span>
                        <select
                          aria-label={`Требуемый уровень: ${item.name}`}
                          value={competencyDraft[item.id]}
                          onChange={(event) =>
                            setCompetencyDraft((current) => ({
                              ...current,
                              [item.id]: Number(event.target.value),
                            }))
                          }
                          className="h-10 rounded-md border border-input bg-background px-3 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {[1, 2, 3, 4, 5].map((level) => (
                            <option key={level} value={level}>
                              {level}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex justify-end">
            <Button type="button" onClick={saveCompetencies} disabled={saving === "competencies"}>
              <Save className="mr-2 h-4 w-4" aria-hidden="true" />
              {saving === "competencies" ? "Сохранение…" : "Сохранить компетенции"}
            </Button>
          </div>
        </section>
      ) : null}

      {activeTab === "training" ? (
        <section aria-labelledby="training-heading" className="space-y-6">
          <div>
            <h2 id="training-heading" className="text-xl font-semibold">
              Обязательное обучение
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Здесь редактируются только прямые правила должности. Правила отдела и покрытие компетенций отображаются
              как источники итогового набора.
            </p>
          </div>
          {catalogError ? (
            <div
              role="alert"
              className="flex flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between"
            >
              <span>{catalogError}</span>
              <Button type="button" variant="outline" onClick={load}>
                <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                Повторить
              </Button>
            </div>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.7fr)]">
            <div className="space-y-3">
              <h3 className="font-semibold">Курсы должности</h3>
              {courseCatalog.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
                  Сначала создайте курс в разделе «Курсы».
                </div>
              ) : (
                <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
                  {courseCatalog.map((course) => {
                    const selected = course.id in trainingDraft;
                    return (
                      <div
                        key={course.id}
                        className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center"
                      >
                        <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={(event) =>
                              setTrainingDraft((current) => {
                                const next = { ...current };
                                if (event.target.checked) next[course.id] = true;
                                else delete next[course.id];
                                return next;
                              })
                            }
                            className="mt-1 h-4 w-4 rounded border-input text-primary focus-visible:ring-2 focus-visible:ring-ring"
                          />
                          <span className="min-w-0">
                            <span className="block break-words font-medium">{course.title}</span>
                            <span className="mt-1 block text-xs text-muted-foreground">
                              {statusLabel(course.status)}
                            </span>
                          </span>
                        </label>
                        {selected ? (
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              type="checkbox"
                              checked={trainingDraft[course.id]}
                              onChange={(event) =>
                                setTrainingDraft((current) => ({
                                  ...current,
                                  [course.id]: event.target.checked,
                                }))
                              }
                              className="h-4 w-4 rounded border-input text-primary focus-visible:ring-2 focus-visible:ring-ring"
                            />
                            Учитывать в готовности
                          </label>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">Выбрано: {selectedCourseCount}</span>
                <Button type="button" onClick={saveTraining} disabled={saving === "training"}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {saving === "training" ? "Применение…" : "Сохранить правила"}
                </Button>
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="font-semibold">Итоговый набор</h3>
              {card.training.effective_courses.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
                  Для должности пока не определено обязательное обучение.
                </div>
              ) : (
                <div className="space-y-2">
                  {card.training.effective_courses.map((course) => (
                    <div key={course.course_id} className="rounded-lg border border-border bg-card p-4">
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0">
                          <Link
                            href={`/courses/${course.course_id}/edit`}
                            className="break-words font-medium hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {course.title}
                          </Link>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {course.sources.map((source) => (
                              <Badge key={source} variant="secondary">
                                {source === "position"
                                  ? "Должность"
                                  : source === "department"
                                    ? "Отдел"
                                    : "Компетенция"}
                              </Badge>
                            ))}
                          </div>
                        </div>
                        <Badge variant={course.status === "published" ? "secondary" : "outline"}>
                          {statusLabel(course.status)}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "onboarding" ? (
        <section aria-labelledby="onboarding-heading" className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="onboarding-heading" className="text-xl font-semibold">
                Onboarding-тест
              </h2>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                Это шаблон теста для должности. Он не назначается новым сотрудникам автоматически: назначение
                выполняется методологом после проверки вопросов.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={generateQuiz} disabled={saving === "quiz-generate"}>
              <Sparkles className="mr-2 h-4 w-4" aria-hidden="true" />
              {saving === "quiz-generate" ? "Создание…" : "Создать черновик из ДИ"}
            </Button>
          </div>

          <div className="space-y-5 rounded-lg border border-border bg-card p-5">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_160px_180px]">
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Название теста</span>
                <input
                  name="onboarding_quiz_title"
                  autoComplete="off"
                  value={quizDraft.title}
                  onChange={(event) =>
                    setQuizDraft((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Проходной балл, %</span>
                <input
                  name="onboarding_pass_score"
                  type="number"
                  min={0}
                  max={100}
                  inputMode="numeric"
                  value={quizDraft.pass_score}
                  onChange={(event) =>
                    setQuizDraft((current) => ({
                      ...current,
                      pass_score: Number(event.target.value),
                    }))
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Время, минут</span>
                <input
                  name="onboarding_time_limit"
                  type="number"
                  min={1}
                  max={600}
                  inputMode="numeric"
                  placeholder="Без ограничения…"
                  value={quizDraft.time_limit}
                  onChange={(event) =>
                    setQuizDraft((current) => ({
                      ...current,
                      time_limit: event.target.value ? Number(event.target.value) : "",
                    }))
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
            </div>

            <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={quizDraft.is_active}
                onChange={(event) =>
                  setQuizDraft((current) => ({
                    ...current,
                    is_active: event.target.checked,
                  }))
                }
                className="h-4 w-4 rounded border-input text-primary focus-visible:ring-2 focus-visible:ring-ring"
              />
              Активный шаблон
            </label>

            <div className="space-y-3">
              {quizDraft.questions.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                  Вопросов пока нет. Создайте черновик из ДИ или добавьте вопрос вручную.
                </div>
              ) : (
                quizDraft.questions.map((question, questionIndex) => (
                  <article key={questionIndex} className="rounded-lg border border-border p-4">
                    <div className="flex items-start gap-3">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold tabular-nums">
                        {questionIndex + 1}
                      </span>
                      <div className="min-w-0 flex-1 space-y-3">
                        <label className="block space-y-1.5">
                          <span className="sr-only">Текст вопроса {questionIndex + 1}</span>
                          <textarea
                            aria-label={`Текст вопроса ${questionIndex + 1}`}
                            rows={2}
                            value={question.text}
                            onChange={(event) =>
                              setQuizDraft((current) => {
                                const questions = [...current.questions];
                                questions[questionIndex] = {
                                  ...questions[questionIndex],
                                  text: event.target.value,
                                };
                                return { ...current, questions };
                              })
                            }
                            className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          />
                        </label>
                        <div className="space-y-2">
                          {question.choices.map((choice, choiceIndex) => (
                            <div key={choiceIndex} className="flex items-center gap-2">
                              <input
                                type="radio"
                                name={`correct-${questionIndex}`}
                                aria-label={`Правильный ответ ${choiceIndex + 1}`}
                                checked={choice.is_correct}
                                onChange={() =>
                                  setQuizDraft((current) => {
                                    const questions = [...current.questions];
                                    questions[questionIndex] = {
                                      ...questions[questionIndex],
                                      choices: questions[questionIndex].choices.map((item, index) => ({
                                        ...item,
                                        is_correct: index === choiceIndex,
                                      })),
                                    };
                                    return { ...current, questions };
                                  })
                                }
                                className="h-4 w-4 border-input text-primary focus-visible:ring-2 focus-visible:ring-ring"
                              />
                              <input
                                aria-label={`Вариант ответа ${choiceIndex + 1}`}
                                value={choice.text}
                                onChange={(event) =>
                                  setQuizDraft((current) => {
                                    const questions = [...current.questions];
                                    const choices = [...questions[questionIndex].choices];
                                    choices[choiceIndex] = {
                                      ...choices[choiceIndex],
                                      text: event.target.value,
                                    };
                                    questions[questionIndex] = {
                                      ...questions[questionIndex],
                                      choices,
                                    };
                                    return { ...current, questions };
                                  })
                                }
                                className="h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              />
                              {question.choices.length > 2 ? (
                                <button
                                  type="button"
                                  aria-label={`Удалить вариант ${choiceIndex + 1}`}
                                  onClick={() =>
                                    setQuizDraft((current) => {
                                      const questions = [...current.questions];
                                      const choices = questions[questionIndex].choices.filter(
                                        (_, index) => index !== choiceIndex,
                                      );
                                      if (!choices.some((item) => item.is_correct)) {
                                        choices[0] = {
                                          ...choices[0],
                                          is_correct: true,
                                        };
                                      }
                                      questions[questionIndex] = {
                                        ...questions[questionIndex],
                                        choices,
                                      };
                                      return { ...current, questions };
                                    })
                                  }
                                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                >
                                  <X className="h-4 w-4" aria-hidden="true" />
                                </button>
                              ) : null}
                            </div>
                          ))}
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              setQuizDraft((current) => {
                                const questions = [...current.questions];
                                questions[questionIndex] = {
                                  ...questions[questionIndex],
                                  choices: [...questions[questionIndex].choices, { text: "", is_correct: false }],
                                };
                                return { ...current, questions };
                              })
                            }
                            disabled={question.choices.length >= 8}
                            className="inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                          >
                            <Plus className="h-4 w-4" aria-hidden="true" />
                            Добавить вариант
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setQuizDraft((current) => ({
                                ...current,
                                questions: current.questions.filter((_, index) => index !== questionIndex),
                              }))
                            }
                            className="inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-destructive hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                            Удалить вопрос
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                ))
              )}
            </div>

            <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  setQuizDraft((current) => ({
                    ...current,
                    questions: [...current.questions, createEmptyQuestion()],
                  }))
                }
                disabled={quizDraft.questions.length >= 30}
              >
                <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
                Добавить вопрос
              </Button>
              <div className="flex flex-wrap justify-end gap-2">
                {card.onboarding_quiz ? (
                  <Button type="button" variant="destructive" onClick={deleteQuiz} disabled={saving === "quiz-delete"}>
                    <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />
                    Удалить тест
                  </Button>
                ) : null}
                <Button type="button" onClick={saveQuiz} disabled={saving === "quiz"}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {saving === "quiz" ? "Сохранение…" : "Сохранить тест"}
                </Button>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "history" ? (
        <section aria-labelledby="history-heading" className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="history-heading" className="text-xl font-semibold">
                История версий
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Каждый снимок содержит профиль, инструкцию, компетенции, курсы и onboarding-тест.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={loadHistory} disabled={historyLoading}>
              <RefreshCw
                className={`mr-2 h-4 w-4 ${historyLoading ? "animate-spin motion-reduce:animate-none" : ""}`}
                aria-hidden="true"
              />
              Обновить
            </Button>
          </div>
          {historyLoading ? (
            <div className="py-12 text-center text-sm text-muted-foreground" aria-live="polite">
              Загрузка истории…
            </div>
          ) : history.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
              <FileClock className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <p className="mt-3 text-sm text-muted-foreground">История появится после первого сохранения карточки.</p>
            </div>
          ) : (
            <ol className="space-y-2">
              {history.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold tabular-nums">Версия {item.version_no}</span>
                      <Badge variant="secondary">{item.change_kind}</Badge>
                    </div>
                    <p className="mt-1 break-words text-sm text-muted-foreground">
                      {item.change_reason || "Причина изменения не указана"}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{formatDate(item.created_at)}</p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => restoreVersion(item)}
                    disabled={saving === `restore-${item.id}`}
                  >
                    <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
                    {saving === `restore-${item.id}` ? "Восстановление…" : "Восстановить"}
                  </Button>
                </li>
              ))}
            </ol>
          )}
        </section>
      ) : null}
      {dialog}
    </div>
  );
}
