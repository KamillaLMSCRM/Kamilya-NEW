"use client";

/**
 * CoursePreview — extracted from /ai/generate/page.tsx (audit §8.3).
 *
 * Two sub-components previously defined inline in the 1261-LOC page:
 *   - ReviewBadge — visual status indicator for course review state.
 *   - CoursePreviewTree — accordion tree of modules → lessons with
 *     inline editing, regenerate, and "ask AI" affordances.
 *
 * Both are pure presentational components; all state and side-effects
 * (chat focus, regenerate, edit submit) live in the parent page and
 * are passed in as callbacks. This keeps the page itself focused on
 * orchestrating the AI generation flow.
 */

import { useState } from "react";
import {
  ChevronRight,
  ClipboardCheck,
  Clock,
  CheckCircle2,
  Loader2,
  MessageSquare,
  PenLine,
  RefreshCw,
  Save,
  XCircle,
} from "lucide-react";


// ── ReviewBadge ───────────────────────────────────────────────────────────────

export function ReviewBadge({
  status,
}: {
  status: "pending" | "approved" | "needs_changes";
}) {
  if (status === "approved") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2.5 py-1 text-xs font-medium text-success"
        aria-label="Одобрено методологом"
      >
        <CheckCircle2 className="w-3 h-3" />
        Одобрено
      </span>
    );
  }
  if (status === "needs_changes") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2.5 py-1 text-xs font-medium text-warning"
        aria-label="Требуются правки"
      >
        <XCircle className="w-3 h-3" />
        Нужны правки
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground"
      aria-label="Ожидает проверки методологом"
    >
      <Clock className="w-3 h-3" />
      На проверке
    </span>
  );
}


// ── CoursePreviewTree ────────────────────────────────────────────────────────

export type CoursePreviewCallbacks = {
  onRegenerateModule: (moduleId: string, title: string) => void;
  onRegenerateLesson: (lessonId: string, title: string) => void;
  onFocusChat: (context: "module" | "lesson", targetId: string) => void;
  onEditLesson: (lessonId: string, title: string, content: string) => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onEditFormChange: (next: { title: string; content: string }) => void;
};

export type CoursePreviewProps = {
  modules: any[];
  busyTargetId: string | null;
  editingLessonId: string | null;
  editForm: { title: string; content: string };
  editSaving: boolean;
} & CoursePreviewCallbacks;


export function CoursePreviewTree({
  modules,
  onRegenerateModule,
  onRegenerateLesson,
  onFocusChat,
  onEditLesson,
  busyTargetId,
  editingLessonId,
  editForm,
  editSaving,
  onCancelEdit,
  onSaveEdit,
  onEditFormChange,
}: CoursePreviewProps) {
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());
  const toggle = (id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  return (
    <ul role="list" className="divide-y divide-border">
      {modules.map((m: any, mi: number) => {
        const isOpen = openIds.has(m.id);
        const moduleBusy = busyTargetId === m.id;
        return (
          <li key={m.id}>
            <div className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors">
              <button
                type="button"
                onClick={() => toggle(m.id)}
                aria-expanded={isOpen}
                className="flex flex-1 items-center gap-3 text-left min-w-0"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-bold text-primary">
                  {mi + 1}
                </span>
                <span className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-foreground truncate">{m.title}</div>
                  {m.description && (
                    <div className="text-xs text-muted-foreground truncate">{m.description}</div>
                  )}
                </span>
                <span className="shrink-0 text-[11px] text-muted-foreground">
                  {m.lessons?.length || 0} ур.
                </span>
                <ChevronRight
                  className={`shrink-0 h-4 w-4 text-muted-foreground transition-transform ${isOpen ? "rotate-90" : ""}`}
                  aria-hidden="true"
                />
              </button>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  type="button"
                  onClick={() => onFocusChat("module", m.id)}
                  className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  title="Спросить AI про этот модуль"
                >
                  <MessageSquare className="w-3 h-3" />
                  Спросить AI
                </button>
                <button
                  type="button"
                  onClick={() => onRegenerateModule(m.id, m.title)}
                  disabled={moduleBusy || !!busyTargetId}
                  className="inline-flex items-center gap-1 rounded-lg border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] font-medium text-warning hover:bg-warning/15 transition-colors disabled:opacity-50"
                >
                  {moduleBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                  Перегенерировать
                </button>
              </div>
            </div>
            {isOpen && (
              <ul role="list" className="bg-muted/30 divide-y divide-border">
                {m.lessons?.length ? (
                  m.lessons.map((l: any, li: number) => {
                    const lessonBusy = busyTargetId === l.id;
                    const isEditing = editingLessonId === l.id;
                    return (
                      <li key={l.id} className="px-4 py-3 pl-14 space-y-1.5">
                        <div className="flex items-start gap-2">
                          <span className="text-xs font-mono text-muted-foreground shrink-0 mt-0.5">{mi + 1}.{li + 1}</span>
                          <div className="flex-1 min-w-0">
                            {isEditing ? (
                              <div className="space-y-2">
                                <input
                                  type="text"
                                  value={editForm.title}
                                  onChange={(e) => onEditFormChange({ ...editForm, title: e.target.value })}
                                  className="w-full rounded-lg border border-primary bg-background px-2 py-1 text-sm font-medium text-foreground focus:outline-none"
                                  placeholder="Название урока"
                                />
                                <textarea
                                  value={editForm.content}
                                  onChange={(e) => onEditFormChange({ ...editForm, content: e.target.value })}
                                  rows={Math.min(15, Math.max(6, editForm.content.split("\n").length + 2))}
                                  className="w-full rounded-lg border border-primary bg-background px-2 py-1.5 text-xs text-foreground font-mono leading-relaxed focus:outline-none resize-y"
                                  placeholder="Содержимое урока"
                                />
                                <div className="flex items-center justify-end gap-2">
                                  <button
                                    type="button"
                                    onClick={onCancelEdit}
                                    disabled={editSaving}
                                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[11px] font-medium text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
                                  >
                                    <XCircle className="w-3 h-3" />
                                    Отмена
                                  </button>
                                  <button
                                    type="button"
                                    onClick={onSaveEdit}
                                    disabled={editSaving || !editForm.title.trim()}
                                    className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                                  >
                                    {editSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                                    Сохранить
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <div className="flex items-center gap-2">
                                  <div className="text-sm font-medium text-foreground truncate flex-1 min-w-0">{l.title}</div>
                                  <button
                                    type="button"
                                    onClick={() => onFocusChat("lesson", l.id)}
                                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors shrink-0"
                                    title="Спросить AI про этот урок"
                                  >
                                    <MessageSquare className="w-2.5 h-2.5" />
                                    AI
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => onEditLesson(l.id, l.title, l.content_preview || "")}
                                    disabled={!!busyTargetId}
                                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-50 shrink-0"
                                    title="Редактировать урок"
                                  >
                                    <PenLine className="w-2.5 h-2.5" />
                                    Изменить
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => onRegenerateLesson(l.id, l.title)}
                                    disabled={lessonBusy || !!busyTargetId}
                                    className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning hover:bg-warning/15 transition-colors disabled:opacity-50 shrink-0"
                                  >
                                    {lessonBusy ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <RefreshCw className="w-2.5 h-2.5" />}
                                    Перегенерировать
                                  </button>
                                </div>
                                {l.content_preview && (
                                  <p className="text-xs text-muted-foreground line-clamp-3 mt-1 whitespace-pre-line">
                                    {l.content_preview}
                                  </p>
                                )}
                                <div className="flex flex-wrap items-center gap-2 mt-1.5">
                                  {l.duration_seconds ? (
                                    <span className="text-[11px] text-muted-foreground">
                                      ⏱ {Math.max(1, Math.round(l.duration_seconds / 60))} мин
                                    </span>
                                  ) : null}
                                  {l.has_quiz && (
                                    <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-[11px] font-medium text-success">
                                      <ClipboardCheck className="w-3 h-3" />
                                      Тест: {l.quiz_question_count || 0} вопр.
                                    </span>
                                  )}
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })
                ) : (
                  <li className="px-4 py-3 pl-14 text-xs text-muted-foreground italic">Нет уроков</li>
                )}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );
}