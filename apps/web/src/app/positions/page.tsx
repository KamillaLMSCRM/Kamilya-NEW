'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface Position {
  id: string;
  name: string;
  department: string;
  level: string;
  responsibilities: string;
  requirements: string;
  course_ids: string[];
  employee_count: number;
  created_at: string;
  re_enrolled?: number;
}

interface Course {
  id: string;
  title: string;
  status: string;
}

// Bulk-JD upload result item (matches backend BulkJDItem)
interface BulkJDItem {
  filename: string;
  name: string;
  department: string;
  level: string;
  responsibilities: string;
  requirements: string;
  error: string | null;
  issues: JDAuditItem[];
  selected: boolean; // for the preview modal
}

// Recommended content item (matches backend RecommendedContentItem)
interface RecommendedItem {
  doc_id: string;
  doc_name: string;
  similarity: number;
  headings: string;
}

// Recommended course item (matches backend RecommendedCourseItem)
interface RecommendedCourse {
  course_id: string;
  title: string;
  similarity: number;
  matched_doc_name: string;
}

// JD preview diff item (matches backend JDPreviewItem)
interface JDPreviewItem {
  field: string;
  current: string;
  proposed: string;
  changed: boolean;
}

// JD version item (matches backend JDVersionItem)
interface JDVersion {
  id: string;
  responsibilities: string;
  requirements: string;
  source: string; // "auto" | "manual"
  note: string | null;
  created_at: string;
  created_by: string | null;
}

// JD audit item (matches backend JDAuditItem)
interface JDAuditItem {
  severity: 'warning' | 'suggestion' | 'ok';
  category: string;
  field: string;
  message: string;
  suggestion: string;
}

// Course suggestion (matches backend CourseSuggestion)
interface CourseSuggestion {
  title: string;
  description: string;
  estimated_chapters: number;
  reason: string;
}

// Onboarding quiz draft (matches backend QuizChoiceDraft / QuizQuestionDraft)
interface QuizChoiceDraft {
  text: string;
  is_correct: boolean;
}
interface QuizQuestionDraft {
  text: string;
  type: string;
  explanation: string;
  choices: QuizChoiceDraft[];
}

// RU pluralization for question count: 1 вопрос, 2-4 вопроса, 5+ вопросов
function pluralQuestions(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 'вопрос';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'вопроса';
  return 'вопросов';
}

// Reusable component: renders a list of audit findings with severity-colored badges.
function JDAuditList({ items, compact = false }: { items: JDAuditItem[]; compact?: boolean }) {
  if (items.length === 0) return null;
  const counts = {
    warning: items.filter((i) => i.severity === 'warning').length,
    suggestion: items.filter((i) => i.severity === 'suggestion').length,
    ok: items.filter((i) => i.severity === 'ok').length,
  };
  return (
    <div className={compact ? 'rounded-lg border border-warning/40 bg-warning/10 p-2.5' : 'rounded-lg border border-warning/40 bg-warning/10/50 p-3'}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm">🔍</span>
        <span className="text-xs font-semibold text-warning">
          AI заметил: {counts.warning > 0 && <span className="text-warning">{counts.warning} замечаний</span>}
          {counts.warning > 0 && counts.suggestion > 0 && ', '}
          {counts.suggestion > 0 && <span className="text-warning">{counts.suggestion} предложений</span>}
          {counts.warning === 0 && counts.suggestion === 0 && counts.ok > 0 && <span className="text-success">{counts.ok} положительных</span>}
        </span>
      </div>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className={`text-xs flex items-start gap-2 ${compact ? '' : 'rounded border border-border bg-card p-2'}`}>
            <span className={`shrink-0 mt-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold ${
              it.severity === 'warning' ? 'bg-destructive/15 text-destructive' :
              it.severity === 'suggestion' ? 'bg-warning/15 text-warning' :
              'bg-success/15 text-success'
            }`}>
              {it.severity === 'warning' ? '!' : it.severity === 'suggestion' ? '?' : '✓'}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-foreground">{it.message}</div>
              {it.suggestion && (
                <div className="text-muted-foreground mt-0.5 italic">→ {it.suggestion}</div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PositionsPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [positions, setPositions] = useState<Position[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editPos, setEditPos] = useState<Position | null>(null);
  const [name, setName] = useState('');
  const [department, setDepartment] = useState('');
  const [level, setLevel] = useState('');
  const [responsibilities, setResponsibilities] = useState('');
  const [requirements, setRequirements] = useState('');
  const [selectedCourseIds, setSelectedCourseIds] = useState<string[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Bulk JD upload state ─────────────────────────────────
  const [bulkAnalyzing, setBulkAnalyzing] = useState(false);
  const [bulkItems, setBulkItems] = useState<BulkJDItem[]>([]);
  const [showBulkPreview, setShowBulkPreview] = useState(false);
  const [bulkCreating, setBulkCreating] = useState(false);
  const bulkFileInputRef = useRef<HTMLInputElement>(null);

  // ── Recommended content state (per position) ─────────────
  const [recsFor, setRecsFor] = useState<string | null>(null);
  const [recs, setRecs] = useState<RecommendedItem[]>([]);
  const [recsLoading, setRecsLoading] = useState(false);

  // ── Recommended courses state (per position) ──────────────
  const [recCourses, setRecCourses] = useState<RecommendedCourse[]>([]);
  const [recCoursesLoading, setRecCoursesLoading] = useState(false);

  // ── JD history state ──────────────────────────────────────
  const [showHistory, setShowHistory] = useState<string | null>(null); // position_id
  const [historyVersions, setHistoryVersions] = useState<JDVersion[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ── JD preview/diff state ─────────────────────────────────
  const [preview, setPreview] = useState<JDPreviewItem[] | null>(null);
  const [previewApplying, setPreviewApplying] = useState(false);

  // ── Generate-from-name state ──────────────────────────────
  const [generating, setGenerating] = useState(false);

  // ── JD audit state ────────────────────────────────────────
  const [auditFor, setAuditFor] = useState<string | null>(null);  // position_id
  const [auditIssues, setAuditIssues] = useState<JDAuditItem[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  // Issues captured from the most recent file upload (so they survive the preview modal)
  const [pendingIssues, setPendingIssues] = useState<JDAuditItem[]>([]);

  // ── Course suggestions state (Phase 2) ──────────────────
  const [suggestionsFor, setSuggestionsFor] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<CourseSuggestion[]>([]);
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<number>>(new Set());
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [creatingCourses, setCreatingCourses] = useState(false);

  // ── Onboarding quiz state (Phase 3) ─────────────────────
  const [quizFor, setQuizFor] = useState<string | null>(null);  // position_id
  const [quizTitle, setQuizTitle] = useState('Онбординг-тест');
  const [quizPassScore, setQuizPassScore] = useState(80);
  const [quizQuestions, setQuizQuestions] = useState<QuizQuestionDraft[]>([]);
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizSaving, setQuizSaving] = useState(false);
  const [quizExists, setQuizExists] = useState(false);  // whether this position already has a saved quiz
  const [quizIsActive, setQuizIsActive] = useState(true);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await api.get('/v1/positions');
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch {} finally {
      setLoading(false);
    }
  }, []);

  const fetchCourses = useCallback(async () => {
    try {
      const res = await api.get('/v1/courses');
      setCourses(Array.isArray(res.data) ? res.data : []);
    } catch {}
  }, []);

  useEffect(() => { fetchPositions(); fetchCourses(); }, [fetchPositions, fetchCourses]);

  const resetForm = () => {
    setName(''); setDepartment(''); setLevel(''); setResponsibilities(''); setRequirements('');
    setSelectedCourseIds([]); setEditPos(null); setShowCreate(false);
  };

  const toggleCourse = (cid: string) => {
    setSelectedCourseIds(prev =>
      prev.includes(cid) ? prev.filter(id => id !== cid) : [...prev, cid]
    );
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    await api.post('/v1/positions', {
      name, department, level, responsibilities, requirements,
      course_ids: selectedCourseIds,
    });
    resetForm();
    fetchPositions();
  };

  const handleEdit = (pos: Position) => {
    setEditPos(pos);
    setName(pos.name);
    setDepartment(pos.department);
    setLevel(pos.level);
    setResponsibilities(pos.responsibilities);
    setRequirements(pos.requirements);
    setSelectedCourseIds(pos.course_ids || []);
    setShowCreate(true);
  };

  const handleUpdate = async () => {
    if (!editPos) return;
    const res = await api.put(`/v1/positions/${editPos.id}`, {
      name, department, level, responsibilities, requirements,
      course_ids: selectedCourseIds,
    });
    const data = res.data as { re_enrolled?: number } | undefined;
    resetForm();
    fetchPositions();
    toast.success(t('toast.positionUpdated'));
    if (data?.re_enrolled && data.re_enrolled > 0) {
      toast.success(t('toast.positionReEnrolled', { count: data.re_enrolled }));
    } else {
      toast.success(t('toast.positionReEnrolledNone'));
    }
  };

  const handleDelete = async (id: string) => {
        const ok = await confirm({
      title: t('dialogs.confirmDeletePosition'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    await api.delete(`/v1/positions/${id}`);
    fetchPositions();
  };

  const handleAnalyzeJD = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAnalyzing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = useAuthStore.getState().accessToken;
      const API_URL = process.env.NEXT_PUBLIC_API_URL;
      const res = await fetch(`${API_URL}/v1/positions/analyze-jd`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Ошибка анализа' }));
        toast.error(t('common.saveFailed'), { description: err.detail || 'Ошибка анализа' });
        return;
      }
      const data = await res.json();
      // If editing existing position, show diff instead of silent overwrite
      if (editPos) {
        const items: JDPreviewItem[] = [
          { field: 'name', current: editPos.name, proposed: data.name || editPos.name, changed: (data.name || '') !== editPos.name },
          { field: 'department', current: editPos.department, proposed: data.department || editPos.department, changed: (data.department || '') !== editPos.department },
          { field: 'level', current: editPos.level, proposed: data.level || editPos.level, changed: (data.level || '') !== editPos.level },
          { field: 'responsibilities', current: editPos.responsibilities, proposed: data.responsibilities || '', changed: (data.responsibilities || '') !== editPos.responsibilities },
          { field: 'requirements', current: editPos.requirements, proposed: data.requirements || '', changed: (data.requirements || '') !== editPos.requirements },
        ];
        setPreview(items);
        setPendingIssues((data.issues as JDAuditItem[]) || []);
        setShowCreate(true); // keep create modal open behind preview
        return;
      }
      // New position: silent auto-fill (current behavior)
      if (data.name) setName(data.name);
      if (data.department) setDepartment(data.department);
      if (data.level) setLevel(data.level);
      if (data.responsibilities) setResponsibilities(data.responsibilities);
      if (data.requirements) setRequirements(data.requirements);
      setShowCreate(true);
    } catch (err) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось проанализировать файл' });
    } finally {
      setAnalyzing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ── Bulk JD upload (multiple files at once) ──────────────
  const handleBulkAnalyzeJD = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length === 0) return;
    if (files.length > 50) {
      toast.error('Максимум 50 файлов за раз');
      return;
    }
    setBulkAnalyzing(true);
    try {
      const formData = new FormData();
      files.forEach(f => formData.append('files', f));
      const token = useAuthStore.getState().accessToken;
      const API_URL = process.env.NEXT_PUBLIC_API_URL;
      const res = await fetch(`${API_URL}/v1/positions/bulk-analyze-jd`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Ошибка анализа' }));
        toast.error(t('common.saveFailed'), { description: err.detail || 'Ошибка анализа' });
        return;
      }
      const data = await res.json();
      const items: BulkJDItem[] = (data.items || []).map((it: any) => ({
        filename: it.filename,
        name: it.name || '',
        department: it.department || '',
        level: it.level || '',
        responsibilities: it.responsibilities || '',
        requirements: it.requirements || '',
        error: it.error || null,
        issues: (it.issues as JDAuditItem[]) || [],
        // Auto-deselect files that failed to parse
        selected: !it.error,
      }));
      setBulkItems(items);
      setShowBulkPreview(true);
      const ok = items.filter((i) => !i.error).length;
      const failed = items.filter((i) => i.error).length;
      // Count audit warnings across all items
      const totalWarnings = items.reduce((sum, i) => sum + (i.issues?.filter(x => x.severity === 'warning').length || 0), 0);
      const totalSuggestions = items.reduce((sum, i) => sum + (i.issues?.filter(x => x.severity === 'suggestion').length || 0), 0);
      if (totalWarnings > 0 || totalSuggestions > 0) {
        toast.success(`Проанализировано: ${ok} успешно, ${failed} с ошибками. AI нашёл ${totalWarnings} замечаний и ${totalSuggestions} предложений.`);
      } else {
        toast.success(`Проанализировано: ${ok} успешно, ${failed} с ошибками`);
      }
    } catch (err) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось проанализировать файлы' });
    } finally {
      setBulkAnalyzing(false);
      if (bulkFileInputRef.current) bulkFileInputRef.current.value = '';
    }
  };

  const handleBulkCreateAll = async () => {
    const toCreate = bulkItems.filter((i) => i.selected && !i.error);
    if (toCreate.length === 0) {
      toast.error('Нет выбранных для создания');
      return;
    }
    setBulkCreating(true);
    try {
      const res = await api.post('/v1/positions/bulk-create', {
        items: toCreate.map((i) => ({
          name: i.name,
          department: i.department,
          level: i.level,
          responsibilities: i.responsibilities,
          requirements: i.requirements,
          course_ids: [],
        })),
      });
      const data = res.data as { created: any[]; failed: any[] };
      toast.success(
        `Создано: ${data.created.length}, ошибок: ${data.failed.length}`,
      );
      setShowBulkPreview(false);
      setBulkItems([]);
      fetchPositions();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || 'Ошибка создания',
      });
    } finally {
      setBulkCreating(false);
    }
  };

  // ── Recommended content (vector search) ──────────────────
  const handleRecommend = async (positionId: string) => {
    setRecsFor(positionId);
    setRecsLoading(true);
    setRecCoursesLoading(true);
    try {
      // Load both in parallel: documents + courses
      const [docRes, courseRes] = await Promise.all([
        api.get(`/v1/positions/${positionId}/recommended-content`, { params: { limit: 5 } }),
        api.get(`/v1/positions/${positionId}/recommended-courses`, { params: { limit: 5 } }).catch(() => ({ data: { items: [] } })),
      ]);
      setRecs(docRes.data.items || []);
      setRecCourses((courseRes.data.items as RecommendedCourse[]) || []);
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось получить рекомендации' });
      setRecs([]);
      setRecCourses([]);
    } finally {
      setRecsLoading(false);
      setRecCoursesLoading(false);
    }
  };

  // ── Generate JD from name only (no file) ────────────────
  const handleGenerateFromName = async () => {
    if (!name.trim()) {
      toast.error('Сначала введите название должности');
      return;
    }
    setGenerating(true);
    try {
      const res = await api.post('/v1/positions/generate-jd-from-name', {
        name: name.trim(),
        department: department.trim(),
        level: level.trim(),
      });
      const data = res.data as { name: string; department: string; level: string; responsibilities: string; requirements: string };
      setName(data.name);
      if (data.department) setDepartment(data.department);
      if (data.level) setLevel(data.level);
      setResponsibilities(data.responsibilities);
      setRequirements(data.requirements);
      toast.success('AI сгенерировал ДИ. Проверьте и отредактируйте.');
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: err?.response?.data?.detail || 'Ошибка генерации' });
    } finally {
      setGenerating(false);
    }
  };

  // ── JD history ─────────────────────────────────────────
  const handleFetchHistory = async (positionId: string) => {
    setShowHistory(positionId);
    setHistoryLoading(true);
    try {
      const res = await api.get(`/v1/positions/${positionId}/jd-versions`);
      setHistoryVersions((res.data.items as JDVersion[]) || []);
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось загрузить историю' });
      setHistoryVersions([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleSnapshotNow = async () => {
    if (!editPos) return;
    try {
      await api.post(`/v1/positions/${editPos.id}/jd-versions`, { note: 'manual snapshot' });
      toast.success('Снимок сохранён');
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось сохранить снимок' });
    }
  };

  const handleRestoreVersion = async (versionId: string) => {
    if (!showHistory) return;
    try {
      await api.post(`/v1/positions/${showHistory}/jd-versions/${versionId}/restore`);
      toast.success('Восстановлено из снимка');
      setShowHistory(null);
      fetchPositions();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось восстановить' });
    }
  };

  // ── JD preview / apply AI suggestions ───────────────────
  const handleApplyPreview = (items: JDPreviewItem[]) => {
    setPreviewApplying(true);
    try {
      for (const it of items) {
        if (!it.changed) continue;
        if (it.field === 'name') setName(it.proposed);
        else if (it.field === 'department') setDepartment(it.proposed);
        else if (it.field === 'level') setLevel(it.proposed);
        else if (it.field === 'responsibilities') setResponsibilities(it.proposed);
        else if (it.field === 'requirements') setRequirements(it.proposed);
      }
      setPreview(null);
      setPendingIssues([]);
      toast.success('Изменения применены');
    } finally {
      setPreviewApplying(false);
    }
  };

  // ── JD audit (re-check saved position) ─────────────────
  const handleAudit = async (positionId: string) => {
    setAuditFor(positionId);
    setAuditLoading(true);
    try {
      const res = await api.post(`/v1/positions/${positionId}/jd-audit`);
      setAuditIssues((res.data.items as JDAuditItem[]) || []);
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось запустить аудит' });
      setAuditIssues([]);
    } finally {
      setAuditLoading(false);
    }
  };

  // ── Course suggestions (Phase 2) ────────────────────────
  const handleSuggestCourses = async (positionId: string) => {
    setSuggestionsFor(positionId);
    setSuggestionsLoading(true);
    setSelectedSuggestions(new Set());  // reset selection
    try {
      const res = await api.post(`/v1/positions/${positionId}/suggest-courses`);
      const items = (res.data.items as CourseSuggestion[]) || [];
      setSuggestions(items);
      // Auto-select all by default (methodologist can deselect what they don't want)
      setSelectedSuggestions(new Set(items.map((_, i) => i)));
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось получить предложения' });
      setSuggestions([]);
    } finally {
      setSuggestionsLoading(false);
    }
  };

  const handleCreateCoursesFromSuggestions = async () => {
    if (!suggestionsFor) return;
    const toCreate = suggestions.filter((_, i) => selectedSuggestions.has(i));
    if (toCreate.length === 0) {
      toast.error('Выберите хотя бы один курс');
      return;
    }
    setCreatingCourses(true);
    try {
      const res = await api.post(`/v1/positions/${suggestionsFor}/create-courses`, {
        items: toCreate.map((s) => ({ title: s.title, description: s.description })),
      });
      const data = res.data as { created: { id: string; title: string }[]; attached_to_position: number };
      toast.success(
        `Создано ${data.created.length} черновик${data.created.length === 1 ? '' : 'ов'} курсов. Наполните контент через «Генерация курсов».`
      );
      setSuggestionsFor(null);
      setSuggestions([]);
      setSelectedSuggestions(new Set());
      fetchPositions();  // refresh to show updated course_ids count
    } catch (err: any) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось создать курсы' });
    } finally {
      setCreatingCourses(false);
    }
  };

  // ── Onboarding quiz (Phase 3) ──────────────────────────
  const openQuizModal = async (positionId: string) => {
    setQuizFor(positionId);
    setQuizLoading(true);
    try {
      // First, fetch existing quiz (if any) to prefill the modal
      const existing = await api.get(`/v1/positions/${positionId}/onboarding-quiz`);
      if (existing.data) {
        const q = existing.data as { title: string; pass_score: number; questions: QuizQuestionDraft[]; is_active: boolean };
        setQuizTitle(q.title);
        setQuizPassScore(q.pass_score);
        setQuizQuestions(q.questions);
        setQuizExists(true);
        setQuizIsActive(q.is_active);
      } else {
        // No saved quiz yet — generate one from JD
        const fresh = await api.post(`/v1/positions/${positionId}/suggest-onboarding-quiz`);
        const data = fresh.data as { title: string; questions: QuizQuestionDraft[] };
        setQuizTitle(data.title || 'Онбординг-тест');
        setQuizPassScore(80);
        setQuizQuestions(data.questions && data.questions.length > 0 ? data.questions : []);
        setQuizExists(false);
        setQuizIsActive(true);
      }
    } catch (err: any) {
      toast.error('Не удалось загрузить онбординг-тест');
      setQuizTitle('Онбординг-тест');
      setQuizPassScore(80);
      setQuizQuestions([]);
      setQuizExists(false);
      setQuizIsActive(true);
    } finally {
      setQuizLoading(false);
    }
  };

  const closeQuizModal = () => {
    setQuizFor(null);
    setQuizQuestions([]);
    setQuizTitle('Онбординг-тест');
    setQuizPassScore(80);
    setQuizExists(false);
    setQuizIsActive(true);
  };

  const updateQuestion = (qi: number, patch: Partial<QuizQuestionDraft>) => {
    setQuizQuestions(prev => prev.map((q, i) => i === qi ? { ...q, ...patch } : q));
  };
  const updateChoice = (qi: number, ci: number, patch: Partial<QuizChoiceDraft>) => {
    setQuizQuestions(prev => prev.map((q, i) => {
      if (i !== qi) return q;
      return { ...q, choices: q.choices.map((c, j) => j === ci ? { ...c, ...patch } : c) };
    }));
  };
  const setCorrectChoice = (qi: number, ci: number) => {
    setQuizQuestions(prev => prev.map((q, i) => {
      if (i !== qi) return q;
      return { ...q, choices: q.choices.map((c, j) => ({ ...c, is_correct: j === ci })) };
    }));
  };
  const addQuestion = () => {
    setQuizQuestions(prev => [...prev, {
      text: '',
      type: 'MCQ',
      explanation: '',
      choices: [
        { text: '', is_correct: true },
        { text: '', is_correct: false },
      ],
    }]);
  };
  const removeQuestion = (qi: number) => {
    setQuizQuestions(prev => prev.filter((_, i) => i !== qi));
  };
  const addChoice = (qi: number) => {
    setQuizQuestions(prev => prev.map((q, i) => {
      if (i !== qi) return q;
      if (q.choices.length >= 8) return q;  // cap at 8
      return { ...q, choices: [...q.choices, { text: '', is_correct: false }] };
    }));
  };
  const removeChoice = (qi: number, ci: number) => {
    setQuizQuestions(prev => prev.map((q, i) => {
      if (i !== qi) return q;
      if (q.choices.length <= 2) return q;  // min 2
      const next = q.choices.filter((_, j) => j !== ci);
      // If we removed the only correct, mark first remaining as correct
      if (!next.some(c => c.is_correct) && next.length > 0) next[0].is_correct = true;
      return { ...q, choices: next };
    }));
  };

  const handleSaveQuiz = async () => {
    if (!quizFor) return;
    // Client-side validation
    for (let i = 0; i < quizQuestions.length; i++) {
      const q = quizQuestions[i];
      if (!q.text.trim()) {
        toast.error(`Вопрос #${i + 1}: введите текст`);
        return;
      }
      if (q.choices.length < 2) {
        toast.error(`Вопрос #${i + 1}: минимум 2 варианта`);
        return;
      }
      if (!q.choices.some(c => c.is_correct)) {
        toast.error(`Вопрос #${i + 1}: отметьте правильный ответ`);
        return;
      }
      if (q.choices.some(c => !c.text.trim())) {
        toast.error(`Вопрос #${i + 1}: все варианты должны иметь текст`);
        return;
      }
    }
    if (quizQuestions.length === 0) {
      toast.error('Добавьте хотя бы один вопрос');
      return;
    }
    setQuizSaving(true);
    try {
      await api.post(`/v1/positions/${quizFor}/onboarding-quiz`, {
        title: quizTitle.trim() || 'Онбординг-тест',
        pass_score: quizPassScore,
        time_limit: null,
        questions: quizQuestions,
        is_active: quizIsActive,
      });
      toast.success(quizExists ? 'Онбординг-тест обновлён' : `Онбординг-тест сохранён (${quizQuestions.length} ${pluralQuestions(quizQuestions.length)})`);
      fetchPositions();
      closeQuizModal();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось сохранить онбординг-тест';
      toast.error(detail);
    } finally {
      setQuizSaving(false);
    }
  };

  const handleDeleteQuiz = async () => {
    if (!quizFor) return;
    const ok = await confirm({
      title: 'Удалить онбординг-тест?',
      message: 'Все вопросы будут удалены безвозвратно.',
      variant: 'danger',
      confirmLabel: 'Удалить',
    });
    if (!ok) return;
    try {
      await api.delete(`/v1/positions/${quizFor}/onboarding-quiz`);
      toast.success('Онбординг-тест удалён');
      fetchPositions();
      closeQuizModal();
    } catch (err: any) {
      toast.error('Не удалось удалить онбординг-тест');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground font-display">Должности</h1>
        <div className="flex gap-2">
          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc,.txt" onChange={handleAnalyzeJD} className="hidden" />
          <input ref={bulkFileInputRef} type="file" accept=".pdf,.docx,.doc,.txt" multiple onChange={handleBulkAnalyzeJD} className="hidden" />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={analyzing}
            className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted transition-colors disabled:opacity-50"
            title="Один JD файл → автозаполнение формы"
          >
            {analyzing ? 'Анализ...' : 'Загрузить JD'}
          </button>
          <button
            onClick={() => bulkFileInputRef.current?.click()}
            disabled={bulkAnalyzing}
            className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-2.5 text-sm font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            title="Несколько JD файлов разом → превью → создать все"
          >
            {bulkAnalyzing ? 'Анализ...' : 'Массовая загрузка JD'}
          </button>
          <button onClick={() => { resetForm(); setShowCreate(true); }} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
            + Добавить должность
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={resetForm} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-lg mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-bold text-foreground font-display mb-4">
              {editPos ? 'Редактировать должность' : 'Новая должность'}
            </h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">Название *</label>
                <div className="flex gap-2">
                  <input value={name} onChange={e => setName(e.target.value)} placeholder="Frontend Developer" className="flex-1 rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
                  <button
                    type="button"
                    onClick={handleGenerateFromName}
                    disabled={generating || !name.trim()}
                    className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors disabled:opacity-50 whitespace-nowrap"
                    title="AI сгенерирует ответственности и требования по названию (без файла)"
                  >
                    {generating ? 'Генерирую...' : '✨ Сгенерировать'}
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground mb-1">Отдел</label>
                  <input value={department} onChange={e => setDepartment(e.target.value)} placeholder="IT" className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground mb-1">Уровень</label>
                  <input value={level} onChange={e => setLevel(e.target.value)} placeholder="middle" className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">Обязанности</label>
                <textarea value={responsibilities} onChange={e => setResponsibilities(e.target.value)} rows={3} placeholder="Что должен делать на этой позиции..." className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">Требования</label>
                <textarea value={requirements} onChange={e => setRequirements(e.target.value)} rows={3} placeholder="Какие знания/навыки нужны..." className="w-full rounded-xl border border-border px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-muted-foreground mb-1">
                  Курсы должности <span className="text-muted-foreground font-normal">(обучающиеся автоматически запишутся)</span>
                </label>
                {courses.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-2">Нет курсов. Создайте курс в разделе «Генерация курсов».</p>
                ) : (
                  <div className="space-y-1.5 max-h-40 overflow-y-auto border border-border rounded-xl p-2">
                    {courses.map(c => (
                      <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-muted cursor-pointer text-sm">
                        <input
                          type="checkbox"
                          checked={selectedCourseIds.includes(c.id)}
                          onChange={() => toggleCourse(c.id)}
                          className="rounded border-border text-primary focus:ring-primary"
                        />
                        <span className="flex-1 truncate">{c.title}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${c.status === 'published' ? 'bg-success/10 text-success' : 'bg-muted text-muted-foreground'}`}>
                          {c.status === 'published' ? 'Опубл.' : 'Черновик'}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={resetForm} className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors">Отмена</button>
              <button onClick={editPos ? handleUpdate : handleCreate} className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
                {editPos ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : positions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
          Нет должностей. Добавьте первую.
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos) => (
            <div key={pos.id} className="rounded-2xl border border-border bg-card p-5 shadow-card hover:shadow-card-hover transition-all">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-bold text-foreground">{pos.name}</h3>
                    {pos.level && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">{pos.level}</span>}
                    {pos.course_ids.length > 0 && (
                      <span className="rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-semibold text-success">
                        {pos.course_ids.length} {pos.course_ids.length === 1 ? 'курс' : 'курса'}
                      </span>
                    )}
                    {pos.employee_count > 0 && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                        {pos.employee_count} обучающихся
                      </span>
                    )}
                  </div>
                  {pos.department && <p className="text-sm text-muted-foreground mt-1">{pos.department}</p>}
                  {pos.responsibilities && <p className="text-sm text-muted-foreground mt-2 line-clamp-2">{pos.responsibilities}</p>}
                  {pos.requirements && <p className="text-xs text-muted-foreground mt-1 line-clamp-1">Требования: {pos.requirements}</p>}

                  {/* AI recommended content panel */}
                  {recsFor === pos.id && (
                    <div className="mt-3 rounded-lg border border-primary/20 bg-primary/5 p-3 space-y-3">
                      {/* Documents */}
                      <div>
                        <div className="text-xs font-semibold text-primary mb-1.5">
                          {recsLoading ? 'Подбираю документы...' : `Документы (${recs.length})`}
                        </div>
                        {recsLoading ? (
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        ) : recs.length === 0 ? (
                          <p className="text-xs text-muted-foreground">
                            {recCourses.length > 0 ? 'Нет похожих документов' : 'Нет похожих документов. Добавьте обязанности/требования к должности.'}
                          </p>
                        ) : (
                          <ul className="space-y-1">
                            {recs.map((r) => (
                              <li key={r.doc_id} className="text-xs flex items-center gap-2">
                                <span className="font-mono text-[10px] text-muted-foreground w-12 text-right">
                                  {(r.similarity * 100).toFixed(0)}%
                                </span>
                                <span className="flex-1 truncate text-foreground">{r.doc_name}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      {/* Courses */}
                      <div>
                        <div className="text-xs font-semibold text-primary mb-1.5">
                          {recCoursesLoading ? 'Подбираю курсы...' : `Курсы (${recCourses.length})`}
                        </div>
                        {recCoursesLoading ? (
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        ) : recCourses.length === 0 ? (
                          <p className="text-xs text-muted-foreground">
                            Не нашлось курсов с похожим контентом
                          </p>
                        ) : (
                          <ul className="space-y-1">
                            {recCourses.map((c) => (
                              <li key={c.course_id} className="text-xs flex items-center gap-2">
                                <span className="font-mono text-[10px] text-muted-foreground w-12 text-right">
                                  {(c.similarity * 100).toFixed(0)}%
                                </span>
                                <span className="flex-1 truncate text-foreground">{c.title}</span>
                                {c.matched_doc_name && (
                                  <span className="text-[10px] text-muted-foreground truncate max-w-[120px]" title={c.matched_doc_name}>
                                    ↳ {c.matched_doc_name}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex gap-2 ml-4">
                  <button onClick={() => handleEdit(pos)} className="rounded-xl border border-border px-3 py-1.5 text-xs text-muted-foreground hover:border-border hover:text-foreground transition-colors">Изменить</button>
                  <button
                    onClick={() => recsFor === pos.id ? setRecsFor(null) : handleRecommend(pos.id)}
                    className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs text-primary hover:bg-primary/10 transition-colors"
                    title="AI подберёт документы и курсы, похожие на обязанности/требования этой должности"
                  >
                    {recsFor === pos.id ? 'Скрыть' : 'Подобрать курсы'}
                  </button>
                  <button
                    onClick={() => showHistory === pos.id ? setShowHistory(null) : handleFetchHistory(pos.id)}
                    className="rounded-xl border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted transition-colors"
                    title="История версий этой должности (авто-снимки + ручные)"
                  >
                    История
                  </button>
                  <button
                    onClick={() => auditFor === pos.id ? setAuditFor(null) : handleAudit(pos.id)}
                    className="rounded-xl border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs text-warning hover:bg-warning/15 transition-colors"
                    title="AI проверит качество этой ДИ (полнота, ясность, compliance) и подсветит замечания"
                  >
                    {auditFor === pos.id ? 'Скрыть' : '🔍 AI-аудит'}
                  </button>
                  <button
                    onClick={() => suggestionsFor === pos.id ? setSuggestionsFor(null) : handleSuggestCourses(pos.id)}
                    className="rounded-xl border border-success/40 bg-success/10 px-3 py-1.5 text-xs text-success hover:bg-success/15 transition-colors"
                    title="AI предложит 3-5 тем курсов для онбординга на эту должность"
                  >
                    {suggestionsFor === pos.id ? 'Скрыть' : '💡 Предложить курсы'}
                  </button>
                  <button
                    onClick={() => quizFor === pos.id ? closeQuizModal() : openQuizModal(pos.id)}
                    className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs text-destructive hover:bg-destructive/15 transition-colors"
                    title="AI создаст онбординг-тест по ДИ: 7 вопросов с вариантами, чтобы новый сотрудник подтвердил понимание"
                  >
                    {quizFor === pos.id ? 'Скрыть' : '📝 Онбординг-тест'}
                  </button>
                  <button onClick={() => handleDelete(pos.id)} className="rounded-xl border border-destructive/40 px-3 py-1.5 text-xs text-destructive hover:border-destructive/40 hover:text-destructive transition-colors">Удалить</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
{dialog}

      {/* Course suggestions modal (after clicking "Предложить курсы" on a saved position) */}
      {suggestionsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setSuggestionsFor(null)} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-2xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-2xl">💡</span>
              <div>
                <h2 className="text-lg font-bold text-foreground font-display">
                  AI предложил курсы для онбординга
                </h2>
                <p className="text-xs text-muted-foreground">
                  Темы созданы на основе ДИ. Выберите какие превратить в черновики, дальше наполните контентом через «Генерация курсов».
                </p>
              </div>
            </div>
            {suggestionsLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-success border-t-transparent" />
              </div>
            ) : suggestions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">
                AI не предложил курсов. Попробуйте сначала заполнить обязанности и требования в ДИ.
              </p>
            ) : (
              <div className="space-y-2">
                {suggestions.map((s, idx) => {
                  const checked = selectedSuggestions.has(idx);
                  return (
                    <label
                      key={idx}
                      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                        checked
                          ? 'border-success/40 bg-success/10'
                          : 'border-border hover:bg-muted'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          const next = new Set(selectedSuggestions);
                          if (e.target.checked) next.add(idx);
                          else next.delete(idx);
                          setSelectedSuggestions(next);
                        }}
                        className="mt-1 rounded border-border text-success focus:ring-success"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-foreground">{s.title}</span>
                          {s.estimated_chapters > 0 && (
                            <span className="rounded-full bg-success/15 text-success px-2 py-0.5 text-[10px] font-semibold">
                              ~{s.estimated_chapters} гл.
                            </span>
                          )}
                        </div>
                        {s.description && (
                          <p className="text-xs text-foreground mt-1">{s.description}</p>
                        )}
                        {s.reason && (
                          <p className="text-[11px] text-success mt-1 italic">💡 {s.reason}</p>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
            <div className="flex gap-2 justify-end mt-5">
              <button
                onClick={() => setSuggestionsFor(null)}
                className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleCreateCoursesFromSuggestions}
                disabled={creatingCourses || selectedSuggestions.size === 0}
                className="rounded-xl bg-success px-4 py-2 text-sm font-medium text-white hover:bg-success transition-colors disabled:opacity-50"
              >
                {creatingCourses
                  ? 'Создаю...'
                  : `Создать ${selectedSuggestions.size} черновик${selectedSuggestions.size === 1 ? '' : selectedSuggestions.size < 5 ? 'а' : 'ов'}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* JD audit modal (after clicking "AI-аудит" on a saved position) */}
      {auditFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setAuditFor(null)} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-2xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-2xl">🔍</span>
              <div>
                <h2 className="text-lg font-bold text-foreground font-display">
                  AI-аудит должностной инструкции
                </h2>
                <p className="text-xs text-muted-foreground">
                  Анализ полноты, ясности и compliance (ОТ, ИБ, ПОД/ФТ) для казахстанской компании
                </p>
              </div>
            </div>
            {auditLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-warning border-t-transparent" />
              </div>
            ) : auditIssues.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">
                AI не нашёл замечаний. (Или ДИ пустая — добавьте обязанности и требования.)
              </p>
            ) : (
              <JDAuditList items={auditIssues} />
            )}
            <div className="flex justify-end mt-5">
              <button
                onClick={() => setAuditFor(null)}
                className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Onboarding quiz modal (Phase 3) — after clicking "Онбординг-тест" on a saved position */}
      {quizFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={closeQuizModal} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-3xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center gap-2 mb-4">
              <span className="text-2xl">📝</span>
              <div className="flex-1">
                <h2 className="text-lg font-bold text-foreground font-display">
                  {quizExists ? 'Редактировать онбординг-тест' : 'AI создал онбординг-тест'}
                </h2>
                <p className="text-xs text-muted-foreground">
                  {quizExists
                    ? 'Измените вопросы и сохраните. Новые сотрудники увидят этот тест при онбординге.'
                    : 'Проверьте вопросы, отредактируйте если нужно, и сохраните. Новые сотрудники увидят этот тест при онбординге.'}
                </p>
              </div>
            </div>
            {quizLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-destructive border-t-transparent" />
              </div>
            ) : (
              <div className="space-y-4">
                {/* Meta: title + pass score */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 rounded-lg border border-border bg-muted p-3">
                  <div className="sm:col-span-2">
                    <label className="block text-[11px] font-semibold text-muted-foreground mb-1">Название теста</label>
                    <input
                      value={quizTitle}
                      onChange={(e) => setQuizTitle(e.target.value)}
                      maxLength={255}
                      className="w-full rounded-lg border border-border px-2.5 py-1.5 text-sm outline-none focus:border-primary"
                      placeholder="Онбординг-тест: ..."
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-muted-foreground mb-1">Проходной балл, %</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={quizPassScore}
                      onChange={(e) => setQuizPassScore(Math.max(0, Math.min(100, parseInt(e.target.value || '0', 10))))}
                      className="w-full rounded-lg border border-border px-2.5 py-1.5 text-sm outline-none focus:border-primary"
                    />
                  </div>
                </div>

                {/* Questions list */}
                {quizQuestions.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-destructive/40 bg-destructive/10 p-4 text-center">
                    <p className="text-sm text-foreground mb-2">
                      AI не сгенерировал вопросов (или ДИ пустая).
                    </p>
                    <p className="text-xs text-muted-foreground mb-3">
                      Заполните обязанности и требования в ДИ, или добавьте вопросы вручную.
                    </p>
                    <button
                      type="button"
                      onClick={addQuestion}
                      className="rounded-lg border border-destructive/40 bg-card px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
                    >
                      + Добавить вопрос вручную
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {quizQuestions.map((q, qi) => (
                      <div key={qi} className="rounded-lg border border-destructive/40 bg-destructive/5 p-3">
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <span className="text-[11px] font-bold text-destructive mt-1.5">#{qi + 1}</span>
                          <textarea
                            value={q.text}
                            onChange={(e) => updateQuestion(qi, { text: e.target.value })}
                            placeholder="Текст вопроса..."
                            rows={2}
                            className="flex-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm outline-none focus:border-primary resize-y"
                          />
                          <button
                            type="button"
                            onClick={() => removeQuestion(qi)}
                            title="Удалить вопрос"
                            className="rounded-lg border border-destructive/40 px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                          >
                            ✕
                          </button>
                        </div>
                        {/* Choices */}
                        <div className="space-y-1.5 ml-7">
                          {q.choices.map((c, ci) => (
                            <div key={ci} className="flex items-start gap-2">
                              <button
                                type="button"
                                onClick={() => setCorrectChoice(qi, ci)}
                                title={c.is_correct ? 'Правильный' : 'Отметить как правильный'}
                                className={`shrink-0 mt-1.5 w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors ${
                                  c.is_correct
                                    ? 'border-success bg-success text-white'
                                    : 'border-border hover:border-foreground/40'
                                }`}
                              >
                                {c.is_correct && <span className="text-[10px]">✓</span>}
                              </button>
                              <input
                                value={c.text}
                                onChange={(e) => updateChoice(qi, ci, { text: e.target.value })}
                                placeholder={`Вариант ${ci + 1}`}
                                className="flex-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm outline-none focus:border-primary"
                              />
                              <button
                                type="button"
                                onClick={() => removeChoice(qi, ci)}
                                disabled={q.choices.length <= 2}
                                title={q.choices.length <= 2 ? 'Минимум 2 варианта' : 'Удалить вариант'}
                                className="shrink-0 rounded-lg border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-30 disabled:hover:bg-transparent"
                              >
                                ✕
                              </button>
                            </div>
                          ))}
                          <button
                            type="button"
                            onClick={() => addChoice(qi)}
                            disabled={q.choices.length >= 8}
                            className="text-[11px] text-destructive hover:text-destructive disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            + Вариант ({q.choices.length}/8)
                          </button>
                        </div>
                        {/* Explanation (optional) */}
                        <div className="ml-7 mt-2">
                          <label className="block text-[10px] font-semibold text-muted-foreground mb-0.5">
                            Объяснение (видно сотруднику после ответа, необязательно)
                          </label>
                          <input
                            value={q.explanation}
                            onChange={(e) => updateQuestion(qi, { explanation: e.target.value })}
                            placeholder="Почему этот ответ правильный..."
                            className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-primary"
                          />
                        </div>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={addQuestion}
                      className="w-full rounded-lg border border-dashed border-destructive/40 px-3 py-2 text-sm text-destructive hover:bg-destructive/10 transition-colors"
                    >
                      + Добавить вопрос ({quizQuestions.length}/30)
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-between gap-2 mt-5 pt-4 border-t border-border">
              <div className="flex items-center gap-2">
                {quizExists && !quizLoading && (
                  <button
                    type="button"
                    onClick={handleDeleteQuiz}
                    className="rounded-xl border border-destructive/40 px-3 py-2 text-xs text-destructive hover:bg-destructive/10 transition-colors"
                  >
                    Удалить тест
                  </button>
                )}
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                  <input
                    type="checkbox"
                    checked={quizIsActive}
                    onChange={(e) => setQuizIsActive(e.target.checked)}
                    className="rounded border-border text-destructive focus:ring-destructive"
                  />
                  Активен (назначать при онбординге)
                </label>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={closeQuizModal}
                  className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={handleSaveQuiz}
                  disabled={quizLoading || quizSaving}
                  className="rounded-xl bg-destructive px-4 py-2 text-sm font-medium text-white hover:bg-destructive transition-colors disabled:opacity-50"
                >
                  {quizSaving ? 'Сохраняю...' : (quizExists ? 'Обновить тест' : `Сохранить тест (${quizQuestions.length})`)}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* JD preview / diff modal (after analyze-jd on existing position) */}
      {preview && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setPreview(null)} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-2xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-bold text-foreground font-display mb-2">
              AI предложил изменения
            </h2>
            <p className="text-sm text-muted-foreground mb-4">
              Сравнение текущих значений с тем, что AI извлёк из JD-файла. Нажмите «Применить» чтобы заменить выбранные поля, или закройте чтобы отклонить.
            </p>
            {pendingIssues.length > 0 && (
              <div className="mb-4">
                <JDAuditList items={pendingIssues} compact />
              </div>
            )}
            <div className="space-y-3">
              {preview.map((it) => (
                <div
                  key={it.field}
                  className={`rounded-lg border p-3 ${
                    it.changed ? 'border-primary/30 bg-primary/5' : 'border-border bg-muted opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-semibold text-foreground">
                      {it.field === 'responsibilities' ? 'Обязанности' :
                       it.field === 'requirements' ? 'Требования' :
                       it.field === 'name' ? 'Название' :
                       it.field === 'department' ? 'Отдел' :
                       it.field === 'level' ? 'Уровень' : it.field}
                    </span>
                    {it.changed ? (
                      <span className="rounded-full bg-primary text-white px-2 py-0.5 text-[10px] font-semibold">
                        изменится
                      </span>
                    ) : (
                      <span className="rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px]">
                        без изменений
                      </span>
                    )}
                  </div>
                  {it.changed && (
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <div className="text-muted-foreground mb-0.5">Было:</div>
                        <div className="text-foreground line-clamp-4 whitespace-pre-wrap">{it.current || '(пусто)'}</div>
                      </div>
                      <div>
                        <div className="text-primary mb-0.5">Станет:</div>
                        <div className="text-foreground line-clamp-4 whitespace-pre-wrap">{it.proposed || '(пусто)'}</div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button
                onClick={() => setPreview(null)}
                className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Отклонить
              </button>
              <button
                onClick={() => handleApplyPreview(preview)}
                disabled={previewApplying}
                className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {previewApplying ? 'Применяю...' : 'Применить изменения'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* JD history modal */}
      {showHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowHistory(null)} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-2xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-bold text-foreground font-display mb-4">
              История версий ДИ
            </h2>
            {historyLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : historyVersions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                Нет снимков. Снимки создаются автоматически при изменении обязанностей/требований.
              </p>
            ) : (
              <div className="space-y-2">
                {historyVersions.map((v) => (
                  <div key={v.id} className="rounded-lg border border-border p-3 hover:border-border">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="text-xs text-muted-foreground">
                        <span className="font-mono">{new Date(v.created_at).toLocaleString('ru-RU')}</span>
                        <span className="ml-2 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-foreground">
                          {v.source === 'manual' ? 'ручной' : 'авто'}
                        </span>
                        {v.note && <span className="ml-2 text-muted-foreground">— {v.note}</span>}
                      </div>
                      <button
                        onClick={() => handleRestoreVersion(v.id)}
                        className="rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10 transition-colors"
                      >
                        Восстановить
                      </button>
                    </div>
                    {v.responsibilities && (
                      <p className="text-xs text-foreground line-clamp-2">
                        <span className="font-semibold">Обязанности:</span> {v.responsibilities}
                      </p>
                    )}
                    {v.requirements && (
                      <p className="text-xs text-foreground line-clamp-1">
                        <span className="font-semibold">Требования:</span> {v.requirements}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2 justify-end mt-5">
              {editPos && showHistory === editPos.id && (
                <button
                  onClick={handleSnapshotNow}
                  className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
                >
                  📌 Снять снимок сейчас
                </button>
              )}
              <button
                onClick={() => setShowHistory(null)}
                className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk JD preview modal */}
      {showBulkPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowBulkPreview(false)} />
          <div className="relative bg-card rounded-2xl shadow-card-lg w-full max-w-3xl mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-bold text-foreground font-display mb-4">
              Превью массовой загрузки ({bulkItems.length} файлов)
            </h2>
            <p className="text-sm text-muted-foreground mb-4">
              Снимите галочку с файлов, которые не нужно создавать. Файлы с ошибками автоматически исключены.
            </p>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {bulkItems.map((it, idx) => (
                <label
                  key={idx}
                  className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    it.error
                      ? 'border-destructive/40 bg-destructive/10 cursor-not-allowed opacity-60'
                      : it.selected
                        ? 'border-primary/30 bg-primary/5'
                        : 'border-border hover:bg-muted'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={it.selected}
                    disabled={!!it.error}
                    onChange={(e) => {
                      const next = [...bulkItems];
                      next[idx] = { ...it, selected: e.target.checked };
                      setBulkItems(next);
                    }}
                    className="mt-1 rounded border-border text-primary focus:ring-primary"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground truncate">
                        {it.name || it.filename}
                      </span>
                      {it.level && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                          {it.level}
                        </span>
                      )}
                      {it.error && (
                        <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-[10px] font-semibold text-destructive">
                          ошибка
                        </span>
                      )}
                      {!it.error && it.issues && it.issues.length > 0 && (
                        <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-semibold text-warning" title={`${it.issues.length} замечаний/предложений от AI`}>
                          🔍 {it.issues.length}
                        </span>
                      )}
                    </div>
                    {it.department && (
                      <p className="text-xs text-muted-foreground mt-0.5">{it.department}</p>
                    )}
                    {it.error && (
                      <p className="text-xs text-destructive mt-1">{it.error}</p>
                    )}
                    {it.responsibilities && (
                      <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                        {it.responsibilities}
                      </p>
                    )}
                    {!it.error && it.issues && it.issues.length > 0 && (
                      <details className="mt-1.5">
                        <summary className="text-[10px] text-warning cursor-pointer hover:text-warning">
                          показать {it.issues.length} замечаний AI
                        </summary>
                        <div className="mt-1.5">
                          <JDAuditList items={it.issues} compact />
                        </div>
                      </details>
                    )}
                    <p className="text-[10px] text-muted-foreground mt-1 truncate">{it.filename}</p>
                  </div>
                </label>
              ))}
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button
                onClick={() => { setShowBulkPreview(false); setBulkItems([]); }}
                className="rounded-xl border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
              >
                Отмена
              </button>
              <button
                onClick={handleBulkCreateAll}
                disabled={bulkCreating || bulkItems.filter((i) => i.selected && !i.error).length === 0}
                className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {bulkCreating
                  ? 'Создаём...'
                  : `Создать ${bulkItems.filter((i) => i.selected && !i.error).length} должностей`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
