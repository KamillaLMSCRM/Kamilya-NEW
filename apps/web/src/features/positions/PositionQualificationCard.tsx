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
import { useT, type TranslationKey } from "@/i18n/useT";

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
  labelKey: string;
  icon: typeof BriefcaseBusiness;
}> = [
  { id: "profile", labelKey: "authenticatedUi.positions.tabs.profile", icon: BriefcaseBusiness },
  { id: "instruction", labelKey: "authenticatedUi.positions.tabs.instruction", icon: FileText },
  { id: "competencies", labelKey: "authenticatedUi.positions.tabs.competencies", icon: ClipboardCheck },
  { id: "training", labelKey: "authenticatedUi.positions.tabs.training", icon: BookOpenCheck },
  // The legacy position quiz editor stays hidden until it has a real
  // assignment, learner-delivery and reporting flow.
  { id: "history", labelKey: "authenticatedUi.positions.tabs.history", icon: History },
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

function formatDate(value: string | null | undefined, locale = "ru-RU") {
  if (!value) return "";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusLabel(status: string, t: (key: TranslationKey) => string) {
  const labels: Record<string, string> = {
    ready: t("authenticatedUi.positions.status.ready" as TranslationKey),
    partial: t("authenticatedUi.positions.status.partial" as TranslationKey),
    processing: t("authenticatedUi.positions.status.processing" as TranslationKey),
    failed: t("authenticatedUi.positions.status.failed" as TranslationKey),
    published: t("authenticatedUi.positions.status.published" as TranslationKey),
    draft: t("authenticatedUi.positions.status.draft" as TranslationKey),
    archived: t("authenticatedUi.positions.status.archived" as TranslationKey),
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
  const { t, lang } = useT();
  const ui = useCallback(
    (key: string, params?: Record<string, string | number>) => t(key as TranslationKey, params),
    [t],
  );
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
        setCatalogError(ui("authenticatedUi.positions.cardCatalogUnavailable"));
      }
      setCard(nextCard);
      setCompetencyCatalog(competencies);
      setCourseCatalog(courses);
      syncDrafts(nextCard);
    } catch (loadError) {
      setError(messageFromError(loadError, ui("authenticatedUi.positions.cardLoadError")));
    } finally {
      setLoading(false);
    }
  }, [positionId, syncDrafts, ui]);

  useEffect(() => {
    load();
  }, [load]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      setHistory(await getQualificationHistory(positionId));
    } catch (historyError) {
      toast.error(messageFromError(historyError, ui("authenticatedUi.positions.historyLoadError")));
    } finally {
      setHistoryLoading(false);
    }
  }, [positionId, ui]);

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
      toast.error(ui("authenticatedUi.positions.nameRequired"));
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
      toast.success(ui("authenticatedUi.positions.profileSaved"));
    } catch (saveError) {
      toast.error(messageFromError(saveError, ui("authenticatedUi.positions.profileSaveError")));
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
      toast.success(ui("authenticatedUi.positions.competenciesSaved"));
    } catch (saveError) {
      toast.error(messageFromError(saveError, ui("authenticatedUi.positions.competenciesSaveError")));
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
      toast.success(ui("authenticatedUi.positions.trainingSaved"));
    } catch (saveError) {
      toast.error(messageFromError(saveError, ui("authenticatedUi.positions.trainingSaveError")));
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
      toast.success(ui("authenticatedUi.positions.instructionUploaded"));
    } catch (uploadError) {
      toast.error(messageFromError(uploadError, ui("authenticatedUi.positions.instructionUploadError")));
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
      toast.error(messageFromError(downloadError, ui("authenticatedUi.positions.instructionDownloadError")));
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
      toast.success(ui("authenticatedUi.positions.quizDraftCreated"));
    } catch (quizError) {
      toast.error(messageFromError(quizError, ui("authenticatedUi.positions.quizDraftError")));
    } finally {
      setSaving(null);
    }
  };

  const saveQuiz = async () => {
    if (!quizDraft.title.trim() || quizDraft.questions.length === 0) {
      toast.error(ui("authenticatedUi.positions.quizRequired"));
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
        ui("authenticatedUi.positions.quizQuestionInvalid", { index: invalidQuestionIndex + 1 }),
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
      toast.success(ui("authenticatedUi.positions.quizSaved"));
    } catch (quizError) {
      toast.error(messageFromError(quizError, ui("authenticatedUi.positions.quizSaveError")));
    } finally {
      setSaving(null);
    }
  };

  const deleteQuiz = async () => {
    const accepted = await confirm({
      title: ui("authenticatedUi.positions.quizDeleteTitle"),
      message: ui("authenticatedUi.positions.quizDeleteMessage"),
      variant: "danger",
      confirmLabel: ui("authenticatedUi.positions.quizDeleteConfirm"),
    });
    if (!accepted) return;
    setSaving("quiz-delete");
    try {
      await api.delete(`/v1/positions/${positionId}/onboarding-quiz`);
      await load();
      toast.success(ui("authenticatedUi.positions.quizDeleted"));
    } catch (quizError) {
      toast.error(messageFromError(quizError, ui("authenticatedUi.positions.quizDeleteError")));
    } finally {
      setSaving(null);
    }
  };

  const restoreVersion = async (item: QualificationHistoryItem) => {
    const accepted = await confirm({
      title: ui("authenticatedUi.positions.restoreTitle", { version: item.version_no }),
      message:
        ui("authenticatedUi.positions.restoreMessage"),
      variant: "warning",
      confirmLabel: ui("authenticatedUi.positions.restoreConfirm"),
    });
    if (!accepted) return;
    setSaving(`restore-${item.id}`);
    try {
      const next = await restoreQualificationVersion(positionId, item.id, ui("authenticatedUi.positions.restoreReason", { version: item.version_no }));
      applyCard(next);
      await loadHistory();
      toast.success(ui("authenticatedUi.positions.restoreSuccess", { version: item.version_no }));
    } catch (restoreError) {
      toast.error(
        messageFromError(restoreError, ui("authenticatedUi.positions.restoreError")),
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
        <span className="sr-only">{ui("authenticatedUi.positions.cardLoading")}</span>
      </div>
    );
  }

  if (error || !card) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="text-xl font-semibold text-foreground">{ui("authenticatedUi.positions.cardUnavailable")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error ?? ui("authenticatedUi.positions.cardNotFound")}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button type="button" onClick={load}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            {ui("authenticatedUi.positions.retry")}
          </Button>
          <Link
            href="/positions"
            className="inline-flex h-10 items-center rounded-md border border-input px-4 text-sm font-medium text-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {ui("authenticatedUi.positions.backToPositions")}
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
          {ui("authenticatedUi.positions.allPositions")}
        </Link>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-2xl font-bold text-foreground sm:text-3xl">{card.profile.name}</h1>
              {card.profile.level ? <Badge variant="secondary">{card.profile.level}</Badge> : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{card.profile.department || ui("authenticatedUi.positions.departmentNotSpecified")}</p>
          </div>

          <dl className="grid min-w-0 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4 xl:min-w-[520px]">
            <div>
              <dt className="text-xs text-muted-foreground">{ui("authenticatedUi.positions.employees")}</dt>
              <dd className="mt-1 flex items-center gap-1.5 font-semibold tabular-nums">
                <Users className="h-4 w-4 text-primary" aria-hidden="true" />
                {card.employees.active_count}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{ui("authenticatedUi.positions.competencies")}</dt>
              <dd className="mt-1 font-semibold tabular-nums">{card.competencies.length}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{ui("authenticatedUi.positions.courses")}</dt>
              <dd className="mt-1 font-semibold tabular-nums">
                {publishedEffectiveCount}/{card.training.effective_courses.length}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">{ui("authenticatedUi.positions.version")}</dt>
              <dd className="mt-1 font-semibold tabular-nums">{card.latest_version ?? "—"}</dd>
            </div>
          </dl>
        </div>
      </header>

      <nav aria-label={ui("authenticatedUi.positions.cardSectionsAria")} className="-mx-1 overflow-x-auto px-1 pb-1">
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
                {ui(tab.labelKey)}
              </button>
            );
          })}
        </div>
      </nav>

      {activeTab === "profile" ? (
        <section aria-labelledby="profile-heading" className="space-y-5">
          <div>
            <h2 id="profile-heading" className="text-xl font-semibold">
              {ui("authenticatedUi.positions.profileTitle")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {ui("authenticatedUi.positions.profileDescription")}
            </p>
          </div>
          <div className="grid gap-5 rounded-lg border border-border bg-card p-5 lg:grid-cols-2">
            <label className="space-y-1.5">
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.name")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.department")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.level")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.responsibilities")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.requirements")}</span>
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
                {ui("authenticatedUi.positions.changeReason")} <span className="font-normal text-muted-foreground">({ui("authenticatedUi.positions.optional")})</span>
              </span>
              <input
                name="profile_change_reason"
                autoComplete="off"
                placeholder={ui("authenticatedUi.positions.changeReasonPlaceholder")}
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
                {saving === "profile" ? ui("authenticatedUi.positions.saving") : ui("authenticatedUi.positions.saveProfile")}
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "instruction" ? (
        <section aria-labelledby="instruction-heading" className="space-y-5">
          <div>
            <h2 id="instruction-heading" className="text-xl font-semibold">
              {ui("authenticatedUi.positions.instructionTitle")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {ui("authenticatedUi.positions.instructionDescription")}
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
                      <Badge variant="secondary">{ui("authenticatedUi.positions.versionValue", { version: card.instruction.version })}</Badge>
                      <Badge variant={card.instruction.index_status === "failed" ? "destructive" : "secondary"}>
                        {statusLabel(card.instruction.index_status, t)}
                      </Badge>
                    </div>
                    <p className="mt-3 text-sm text-muted-foreground">
                      {ui("authenticatedUi.positions.updatedAt", { date: formatDate(card.instruction.updated_at, lang) })}
                    </p>
                    {card.instruction.index_error_code ? (
                      <p className="mt-2 text-sm text-destructive">
                        {ui("authenticatedUi.positions.indexingError")}
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
                    {ui("authenticatedUi.positions.download")}
                  </Button>
                  <Button type="button" onClick={() => uploadRef.current?.click()} disabled={saving === "instruction"}>
                    <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
                    {saving === "instruction" ? ui("authenticatedUi.positions.uploading") : ui("authenticatedUi.positions.uploadNewVersion")}
                  </Button>
                </div>
              </div>
              <div className="mt-5 border-t border-border pt-4">
                <Link
                  href={`/documents?search=${encodeURIComponent(card.instruction.filename)}`}
                  className="text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {ui("authenticatedUi.positions.openDocumentLibrary")}
                </Link>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border px-5 py-12 text-center">
              <FileText className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <h3 className="mt-3 font-semibold">{ui("authenticatedUi.positions.instructionEmptyTitle")}</h3>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                {ui("authenticatedUi.positions.instructionEmptyDescription")}
              </p>
              <Button
                type="button"
                className="mt-5"
                onClick={() => uploadRef.current?.click()}
                disabled={saving === "instruction"}
              >
                <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
                {saving === "instruction" ? ui("authenticatedUi.positions.uploading") : ui("authenticatedUi.positions.uploadDocument")}
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
              {ui("authenticatedUi.positions.competenciesTitle")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
              {ui("authenticatedUi.positions.competenciesDescription")}
              </p>
            </div>
            <Link
              href="/competencies"
              className="text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {ui("authenticatedUi.positions.openCompetencyCatalog")}
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
                {ui("authenticatedUi.positions.retry")}
              </Button>
            </div>
          ) : null}
          {competencyCatalog.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
              <p className="text-sm text-muted-foreground">{ui("authenticatedUi.positions.competenciesEmpty")}</p>
              <Link
                href="/competencies"
                className="mt-4 inline-flex h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {ui("authenticatedUi.positions.createCompetency")}
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
                        <span className="text-muted-foreground">{ui("authenticatedUi.positions.requiredLevel")}</span>
                        <select
                          aria-label={ui("authenticatedUi.positions.requiredLevelAria", { name: item.name })}
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
              {saving === "competencies" ? ui("authenticatedUi.positions.saving") : ui("authenticatedUi.positions.saveCompetencies")}
            </Button>
          </div>
        </section>
      ) : null}

      {activeTab === "training" ? (
        <section aria-labelledby="training-heading" className="space-y-6">
          <div>
            <h2 id="training-heading" className="text-xl font-semibold">
              {ui("authenticatedUi.positions.trainingTitle")}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {ui("authenticatedUi.positions.trainingDescription")}
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
                {ui("authenticatedUi.positions.retry")}
              </Button>
            </div>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.7fr)]">
            <div className="space-y-3">
              <h3 className="font-semibold">{ui("authenticatedUi.positions.positionCourses")}</h3>
              {courseCatalog.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
                  {ui("authenticatedUi.positions.noCoursesHint")}
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
                              {statusLabel(course.status, t)}
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
                            {ui("authenticatedUi.positions.includeInReadiness")}
                          </label>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">{ui("authenticatedUi.positions.selectedCourses", { count: selectedCourseCount })}</span>
                <Button type="button" onClick={saveTraining} disabled={saving === "training"}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {saving === "training" ? ui("authenticatedUi.positions.applying") : ui("authenticatedUi.positions.saveRules")}
                </Button>
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="font-semibold">{ui("authenticatedUi.positions.effectiveSet")}</h3>
              {card.training.effective_courses.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
                  {ui("authenticatedUi.positions.noEffectiveTraining")}
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
                                  ? ui("authenticatedUi.positions.sourcePosition")
                                  : source === "department"
                                    ? ui("authenticatedUi.positions.sourceDepartment")
                                    : ui("authenticatedUi.positions.sourceCompetency")}
                              </Badge>
                            ))}
                          </div>
                        </div>
                        <Badge variant={course.status === "published" ? "secondary" : "outline"}>
                          {statusLabel(course.status, t)}
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
                {ui("authenticatedUi.positions.quizTitle")}
              </h2>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
                {ui("authenticatedUi.positions.quizDescription")}
              </p>
            </div>
            <Button type="button" variant="outline" onClick={generateQuiz} disabled={saving === "quiz-generate"}>
              <Sparkles className="mr-2 h-4 w-4" aria-hidden="true" />
              {saving === "quiz-generate" ? ui("authenticatedUi.positions.creating") : ui("authenticatedUi.positions.createQuizDraft")}
            </Button>
          </div>

          <div className="space-y-5 rounded-lg border border-border bg-card p-5">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_160px_180px]">
              <label className="space-y-1.5">
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.quizName")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.passingScore")}</span>
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
                <span className="text-sm font-medium">{ui("authenticatedUi.positions.timeLimit")}</span>
                <input
                  name="onboarding_time_limit"
                  type="number"
                  min={1}
                  max={600}
                  inputMode="numeric"
                  placeholder={ui("authenticatedUi.positions.noTimeLimit")}
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
              {ui("authenticatedUi.positions.activeTemplate")}
            </label>

            <div className="space-y-3">
              {quizDraft.questions.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                  {ui("authenticatedUi.positions.noQuestions")}
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
                          <span className="sr-only">{ui("authenticatedUi.positions.questionText", { index: questionIndex + 1 })}</span>
                          <textarea
                            aria-label={ui("authenticatedUi.positions.questionText", { index: questionIndex + 1 })}
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
                                aria-label={ui("authenticatedUi.positions.correctAnswer", { index: choiceIndex + 1 })}
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
                                aria-label={ui("authenticatedUi.positions.answerOption", { index: choiceIndex + 1 })}
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
                                  aria-label={ui("authenticatedUi.positions.removeOption", { index: choiceIndex + 1 })}
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
                            {ui("authenticatedUi.positions.addOption")}
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
                            {ui("authenticatedUi.positions.removeQuestion")}
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
                {ui("authenticatedUi.positions.addQuestion")}
              </Button>
              <div className="flex flex-wrap justify-end gap-2">
                {card.onboarding_quiz ? (
                  <Button type="button" variant="destructive" onClick={deleteQuiz} disabled={saving === "quiz-delete"}>
                    <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />
                    {ui("authenticatedUi.positions.deleteQuiz")}
                  </Button>
                ) : null}
                <Button type="button" onClick={saveQuiz} disabled={saving === "quiz"}>
                  <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                  {saving === "quiz" ? ui("authenticatedUi.positions.saving") : ui("authenticatedUi.positions.saveQuiz")}
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
                {ui("authenticatedUi.positions.historyTitle")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {ui("authenticatedUi.positions.historyDescription")}
              </p>
            </div>
            <Button type="button" variant="outline" onClick={loadHistory} disabled={historyLoading}>
              <RefreshCw
                className={`mr-2 h-4 w-4 ${historyLoading ? "animate-spin motion-reduce:animate-none" : ""}`}
                aria-hidden="true"
              />
              {ui("authenticatedUi.positions.refresh")}
            </Button>
          </div>
          {historyLoading ? (
            <div className="py-12 text-center text-sm text-muted-foreground" aria-live="polite">
              {ui("authenticatedUi.positions.historyLoading")}
            </div>
          ) : history.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
              <FileClock className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <p className="mt-3 text-sm text-muted-foreground">{ui("authenticatedUi.positions.historyEmpty")}</p>
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
                      <span className="font-semibold tabular-nums">{ui("authenticatedUi.positions.versionValue", { version: item.version_no })}</span>
                      <Badge variant="secondary">{item.change_kind}</Badge>
                    </div>
                    <p className="mt-1 break-words text-sm text-muted-foreground">
                      {item.change_reason || ui("authenticatedUi.positions.changeReasonMissing")}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{formatDate(item.created_at, lang)}</p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => restoreVersion(item)}
                    disabled={saving === `restore-${item.id}`}
                  >
                    <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
                    {saving === `restore-${item.id}` ? ui("authenticatedUi.positions.restoring") : ui("authenticatedUi.positions.restoreConfirm")}
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
