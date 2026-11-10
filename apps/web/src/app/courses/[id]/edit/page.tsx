'use client';

import Link from 'next/link';
import { sourceReviewHref, sourceReviewPins } from '@/features/source-editorial-review/contract';
import { sourceReviewCopy } from '@/features/source-editorial-review/copy';

import { useState, useEffect, useCallback, useMemo, useRef, type MouseEvent as ReactMouseEvent } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent, Button, Input, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronUp,
  Eye,
  FileText,
  ListTree,
  LoaderCircle,
  Pencil,
  Rocket,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { AIChatPanel } from '@/components/ai/AIChatPanel';
import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { coursePublicationError } from '@/lib/coursePublicationError';
import { LessonContent } from '@/features/course-authoring/LessonContent';
import { MarkdownToolbar } from '@/features/course-authoring/MarkdownToolbar';
import { CourseReadiness } from '@/features/course-authoring/CourseReadiness';
import { SourceReviewPanel } from '@/features/course-authoring/SourceReviewPanel';
import { WorkspacePage, WorkspacePageHeader, WorkspaceToolbar } from '@/features/workspace-design';
import { authorWorkspaceCopy } from '@/features/course-authoring/authorWorkspaceCopy';
import { currentAuthorSession, sameAuthorSession } from '@/features/course-authoring/authorSession';
import { authorRead } from '@/features/course-authoring/authorRead';
import LessonCorrectionPanel, { type LessonCorrectionPanelHandle } from '@/features/methodologist-workbench/LessonCorrectionPanel';
import type { CorrectionApplicationReceipt } from '@/lib/lessonCorrection';

interface Lesson {
  id: string;
  title: string;
  content_type: string;
  order_index: number;
}

interface Module {
  id: string;
  title: string;
  description: string;
  order_index: number;
  lessons: Lesson[];
}

interface Course {
  id: string;
  title: string;
  description: string;
  status: string;
  ai_generated: boolean;
  review_status: 'pending' | 'approved' | 'needs_changes';
  requires_approval?: boolean;
  source_instruction_id?: string | null;
  source_analysis?: { blueprint?: Record<string, unknown> | null; source_editorial_snapshots?: unknown; unplaced_source_assets?: unknown } | null;
}

export default function CourseEditPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params?.id as string;
  const { t, lang } = useT();
  const copy = authorWorkspaceCopy(lang);
  const { confirm, dialog } = useConfirm();
  const token = useAuthStore((s) => s.accessToken);
  const actor = useAuthStore((s) => s.user);
  const sessionEpoch = useAuthStore((s) => s.sessionEpoch);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const latestTokenRef = useRef(token);
  latestTokenRef.current = token;
  const authRef = useRef({ accessToken: token, user: actor, sessionEpoch });
  authRef.current = { accessToken: token, user: actor, sessionEpoch };
  const session = currentAuthorSession(authRef.current);
  const workspaceScope = useMemo(() => ({
    courseId, session,
  }), [courseId, session]);
  const scopeRef = useRef({ identity: workspaceScope, generation: 0 });
  if (scopeRef.current.identity !== workspaceScope) {
    scopeRef.current = { identity: workspaceScope, generation: scopeRef.current.generation + 1 };
  }
  const metadataGenerationRef = useRef(0);
  const saveGenerationRef = useRef(0);
  const actionGenerationRef = useRef(new Map<string, number>());
  const dataScopeRef = useRef<typeof workspaceScope | null>(null);
  const isScopeCurrent = useCallback((captured: { identity: typeof workspaceScope; generation: number }) => {
    return captured.identity === scopeRef.current.identity && captured.generation === scopeRef.current.generation
      && sameAuthorSession(captured.identity.session, currentAuthorSession(authRef.current));
  }, []);
  const beginAction = useCallback((key: string) => {
    const captured = { ...scopeRef.current };
    if (captured.identity !== workspaceScope || !isScopeCurrent(captured)) return () => false;
    const generation = (actionGenerationRef.current.get(key) ?? 0) + 1;
    actionGenerationRef.current.set(key, generation);
    return () => captured.identity === workspaceScope && isScopeCurrent(captured) && actionGenerationRef.current.get(key) === generation;
  }, [workspaceScope, isScopeCurrent]);

  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [readinessUnavailable, setReadinessUnavailable] = useState(true);
  const lessonTextareaRef = useRef<HTMLTextAreaElement>(null);
  const initialLessonRef = useRef<string | null>(null);
  const [newModuleTitle, setNewModuleTitle] = useState('');
  const [editingModuleId, setEditingModuleId] = useState<string | null>(null);
  const [editModuleTitle, setEditModuleTitle] = useState('');
  const [newLessonTitle, setNewLessonTitle] = useState('');
  const [addingLessonToModule, setAddingLessonToModule] = useState<string | null>(null);
  const [editingLessonId, setEditingLessonId] = useState<string | null>(null);
  const [editLessonTitle, setEditLessonTitle] = useState('');
  const [editLessonContent, setEditLessonContent] = useState('');
  const [savedLessonTitle, setSavedLessonTitle] = useState('');
  const [savedLessonContent, setSavedLessonContent] = useState('');
  const [lessonView, setLessonView] = useState<'edit' | 'preview'>('edit');
  const [loadingLessonId, setLoadingLessonId] = useState<string | null>(null);
  const [creationBusy, setCreationBusy] = useState(false);
  const creationPending = useRef<symbol | null>(null);
  const [creationError, setCreationError] = useState<{ target: string; message: string } | null>(null);
  const [savingLesson, setSavingLesson] = useState(false);
  const [releaseAction, setReleaseAction] = useState<'approve' | 'publish' | null>(null);
  const [programGenerationJob, setProgramGenerationJob] = useState<string | null>(null);
  const [correctionBusy, setCorrectionBusy] = useState(false);
  const correctionBusyRef = useRef(false);
  const correctionPanelRef = useRef<LessonCorrectionPanelHandle>(null);

  // AI chat panel state — opens as a slide-over from the right.
  const [chatOpen, setChatOpen] = useState(false);
  const [chatFocus, setChatFocus] = useState<{
    lessonId?: string;
    lessonTitle?: string;
    moduleId?: string;
    moduleTitle?: string;
  }>({});

  const activeLesson = useMemo(
    () => modules.flatMap((module) => module.lessons).find((lesson) => lesson.id === editingLessonId) ?? null,
    [editingLessonId, modules],
  );
  const lessonSequence = modules.flatMap((module) => module.lessons);
  const activeLessonIndex = lessonSequence.findIndex((lesson) => lesson.id === editingLessonId);
  const activeModule = modules.find((module) => module.lessons.some((lesson) => lesson.id === editingLessonId));
  const lessonDirty = Boolean(editingLessonId)
    && (editLessonTitle !== savedLessonTitle || editLessonContent !== savedLessonContent);
  const moduleDirty = Boolean(editingModuleId)
    && editModuleTitle !== modules.find((module) => module.id === editingModuleId)?.title;
  const workspaceDirty = lessonDirty || moduleDirty;
  useEffect(() => {
    setProgramGenerationJob(new URLSearchParams(window.location.search).get('programGenerationJob'));
  }, [courseId]);
  const editorSnapshot = useRef({ courseId, editingLessonId, token, editLessonTitle, savedLessonTitle, editLessonContent, savedLessonContent, savingLesson, loadingLessonId });
  editorSnapshot.current = { courseId, editingLessonId, token, editLessonTitle, savedLessonTitle, editLessonContent, savedLessonContent, savingLesson, loadingLessonId };
  const onCorrectionApplied = (receipt: CorrectionApplicationReceipt, content: string, before: string) => {
    const current = editorSnapshot.current;
    if (current.courseId !== receipt.course_id || current.editingLessonId !== receipt.lesson_id
      || current.token !== useAuthStore.getState().accessToken || current.savingLesson || current.loadingLessonId
      || current.editLessonTitle !== current.savedLessonTitle || current.editLessonContent !== current.savedLessonContent
      || current.savedLessonContent !== before) return;
    setSavedLessonContent(content); setEditLessonContent(content);
    setCourse((value) => value?.id === receipt.course_id ? { ...value, review_status: 'pending' } : value);
  };
  const onCorrectionApplyingChange = (busy: boolean) => {
    correctionBusyRef.current = busy; setCorrectionBusy(busy);
  };

  useEffect(() => {
    if (!workspaceDirty && !correctionBusy) return;
    const guardUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', guardUnload);
    return () => window.removeEventListener('beforeunload', guardUnload);
  }, [workspaceDirty, correctionBusy]);

  useEffect(() => {
    if (!workspaceDirty && !correctionBusy) return;

    const guardInternalNavigation = (event: MouseEvent) => {
      if (
        event.defaultPrevented
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
      ) return;

      const target = event.target;
      if (!(target instanceof Element)) return;
      const link = target.closest<HTMLAnchorElement>('a[href]');
      if (!link || link.target === '_blank' || link.hasAttribute('download')) return;

      const href = link.getAttribute('href');
      if (!href || href.startsWith('#')) return;

      const destination = new URL(link.href, window.location.href);
      if (destination.origin !== window.location.origin) return;

      event.preventDefault();
      event.stopPropagation();
      if (correctionBusyRef.current) return;
      void confirm({
        title: t('authenticatedUi.editor.unsavedTitle'),
        message: t('authenticatedUi.editor.unsavedDescription'),
        confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
        variant: 'danger',
      }).then((discard) => {
        if (discard) {
          router.push(`${destination.pathname}${destination.search}${destination.hash}`);
        }
      });
    };

    document.addEventListener('click', guardInternalNavigation, true);
    return () => document.removeEventListener('click', guardInternalNavigation, true);
  }, [confirm, workspaceDirty, correctionBusy, router, t]);

  const fetchData = useCallback(async () => {
    if (!courseId || !latestTokenRef.current) return;
    const captured = { ...scopeRef.current };
    if (captured.identity !== workspaceScope || !isScopeCurrent(captured)) return;
    const generation = ++metadataGenerationRef.current;
    const isCurrentRead = () => isScopeCurrent(captured) && generation === metadataGenerationRef.current;
    setReadinessUnavailable(true);
    try {
      const [courseRes, structRes] = await Promise.all([
        authorRead(`${API_URL}/v1/courses/${courseId}`, captured.identity.session),
        authorRead(`${API_URL}/v1/courses/${courseId}/structure`, captured.identity.session),
      ]);
      if (!courseRes.ok || !structRes.ok) throw new Error('Workspace load failed');
      const [courseData, structureData] = await Promise.all([courseRes.json(), structRes.json()]);
      if (!isCurrentRead()) return;
      if (courseData.id !== captured.identity.courseId) throw new Error('Course identity mismatch');
      setCourse(courseData);
      setModules(structureData.modules || []);
      setLoadError(false);
      setReadinessUnavailable(false);
    } catch {
      if (isCurrentRead()) setLoadError(true);
    } finally {
      if (isCurrentRead()) setLoading(false);
    }
  }, [courseId, API_URL, workspaceScope, isScopeCurrent]);

  useEffect(() => {
    dataScopeRef.current = workspaceScope;
    setCourse(null); setModules([]); setEditingLessonId(null);
    setEditLessonTitle(''); setEditLessonContent(''); setSavedLessonTitle(''); setSavedLessonContent('');
    setLoadingLessonId(null); setSavingLesson(false); setReleaseAction(null);
    setNewModuleTitle(''); setEditingModuleId(null); setEditModuleTitle('');
    setNewLessonTitle(''); setAddingLessonToModule(null);
    creationPending.current = null; setCreationBusy(false); setCreationError(null);
    setChatOpen(false); setChatFocus({}); setCorrectionBusy(false); correctionBusyRef.current = false;
    setLoadError(false); setReadinessUnavailable(true); setLoading(true);
    initialLessonRef.current = null;
    void fetchData();
    return () => { scopeRef.current.generation += 1; metadataGenerationRef.current += 1; };
  }, [fetchData, workspaceScope]);

  const handleAddModule = async () => {
    if (creationPending.current) return;
    const isCurrent = beginAction('add-module');
    if (!newModuleTitle.trim() || !latestTokenRef.current || !isCurrent()) return;
    const creationRequest = Symbol();
    creationPending.current = creationRequest;
    setCreationBusy(true);
    setCreationError(null);
    try {
      const res = await fetch(`${API_URL}/v1/courses/${courseId}/modules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
        body: JSON.stringify({ title: newModuleTitle }),
      });
      if (!res.ok) throw new Error('Module creation failed');
      const mod = await res.json();
      if (!isCurrent()) return;
      setModules((prev) => [...prev, { ...mod, lessons: [] }]);
      setNewModuleTitle('');
    } catch {
      if (isCurrent()) setCreationError({ target: 'module', message: `${t('common.saveFailed')}. ${copy.creationFailure}` });
    } finally {
      if (creationPending.current === creationRequest) {
        creationPending.current = null;
        if (isCurrent()) setCreationBusy(false);
      }
    }
  };

  const handleEditModule = async (module: Module) => {
    if (moduleDirty) {
      const discard = await confirm({
        title: t('authenticatedUi.editor.unsavedTitle'),
        message: t('authenticatedUi.editor.unsavedDescription'),
        confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
        variant: 'danger',
      });
      if (!discard) return;
    }
    setEditingModuleId(module.id);
    setEditModuleTitle(module.title);
  };

  const handleUpdateModule = async (moduleId: string) => {
    const isCurrent = beginAction(`update-module:${moduleId}`);
    if (!editModuleTitle.trim() || !latestTokenRef.current || !isCurrent()) return;
    try {
      const res = await fetch(`${API_URL}/v1/modules/${moduleId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
        body: JSON.stringify({ title: editModuleTitle }),
      });
      if (!res.ok) {
        if (isCurrent()) toast.error(t('common.saveFailed'));
        return;
      }
      const savedModule = await res.json() as { title?: unknown };
      if (!isCurrent()) return;
      const savedTitle = typeof savedModule.title === 'string' && savedModule.title.trim()
        ? savedModule.title
        : editModuleTitle;
      setModules((prev) => prev.map((m) => m.id === moduleId ? { ...m, title: savedTitle } : m));
      setEditingModuleId(null);
    } catch {
      if (isCurrent()) toast.error(t('common.saveFailed'));
    }
  };

  const handleDeleteModule = async (moduleId: string) => {
    const isCurrent = beginAction(`delete-module:${moduleId}`);
    if (!latestTokenRef.current || !isCurrent()) return;
    const removesActiveLesson = modules
      .find((module) => module.id === moduleId)
      ?.lessons.some((lesson) => lesson.id === editingLessonId) ?? false;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteModule'),
      message: removesActiveLesson && lessonDirty
        ? t('authenticatedUi.editor.unsavedDescription')
        : undefined,
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok || !isCurrent()) return;
    try {
      const res = await fetch(`${API_URL}/v1/modules/${moduleId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${latestTokenRef.current}` },
      });
      if (!res.ok) {
        if (isCurrent()) toast.error(t('common.deleteFailed'));
        return;
      }
      if (!isCurrent()) return;
      setModules((prev) => prev.filter((m) => m.id !== moduleId));
      if (removesActiveLesson) setEditingLessonId(null);
    } catch {
      if (isCurrent()) toast.error(t('common.deleteFailed'));
    }
  };

  const handleAddLesson = async (moduleId: string) => {
    if (creationPending.current) return;
    const isCurrent = beginAction(`add-lesson:${moduleId}`);
    if (!newLessonTitle.trim() || !latestTokenRef.current || !isCurrent()) return;
    const creationRequest = Symbol();
    creationPending.current = creationRequest;
    setCreationBusy(true);
    setCreationError(null);
    try {
      const res = await fetch(`${API_URL}/v1/modules/${moduleId}/lessons`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
        body: JSON.stringify({ title: newLessonTitle, content_type: 'text' }),
      });
      if (!res.ok) throw new Error('Lesson creation failed');
      const lesson = await res.json();
      if (!isCurrent()) return;
      setModules((prev) => prev.map((m) =>
        m.id === moduleId ? { ...m, lessons: [...m.lessons, lesson] } : m
      ));
      setNewLessonTitle('');
      setAddingLessonToModule(null);
    } catch {
      if (isCurrent()) setCreationError({ target: moduleId, message: `${t('common.saveFailed')}. ${copy.creationFailure}` });
    } finally {
      if (creationPending.current === creationRequest) {
        creationPending.current = null;
        if (isCurrent()) setCreationBusy(false);
      }
    }
  };

  const handleDeleteLesson = async (lessonId: string, moduleId: string) => {
    const isCurrent = beginAction(`delete-lesson:${lessonId}`);
    if (!latestTokenRef.current || !isCurrent()) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteLesson'),
      message: editingLessonId === lessonId && lessonDirty
        ? t('authenticatedUi.editor.unsavedDescription')
        : undefined,
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok || !isCurrent()) return;
    try {
      const res = await fetch(`${API_URL}/v1/lessons/${lessonId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${latestTokenRef.current}` },
      });
      if (!res.ok) {
        if (isCurrent()) toast.error(t('common.deleteFailed'));
        return;
      }
      if (!isCurrent()) return;
      setModules((prev) => prev.map((m) =>
        m.id === moduleId ? { ...m, lessons: m.lessons.filter((l) => l.id !== lessonId) } : m
      ));
      if (editingLessonId === lessonId) setEditingLessonId(null);
    } catch {
      if (isCurrent()) toast.error(t('common.deleteFailed'));
    }
  };

  const handleMoveModule = async (moduleId: string, direction: 'up' | 'down') => {
    const isCurrent = beginAction('reorder-modules');
    if (!isCurrent()) return;
    const idx = modules.findIndex((m) => m.id === moduleId);
    if (idx < 0) return;
    const newIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (newIdx < 0 || newIdx >= modules.length) return;
    const reordered = [...modules];
    [reordered[idx], reordered[newIdx]] = [reordered[newIdx], reordered[idx]];
    setModules(reordered);
    // Persist reorder
    if (latestTokenRef.current && isCurrent()) {
      await fetch(`${API_URL}/v1/courses/${courseId}/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
        body: JSON.stringify(reordered.map((m) => m.id)),
      });
    }
  };

  const handleMoveLesson = async (lessonId: string, moduleId: string, direction: 'up' | 'down') => {
    const isCurrent = beginAction(`reorder-lessons:${moduleId}`);
    if (!isCurrent()) return;
    const modIdx = modules.findIndex((m) => m.id === moduleId);
    if (modIdx < 0) return;
    const lessonIdx = modules[modIdx].lessons.findIndex((l) => l.id === lessonId);
    if (lessonIdx < 0) return;
    const newIdx = direction === 'up' ? lessonIdx - 1 : lessonIdx + 1;
    if (newIdx < 0 || newIdx >= modules[modIdx].lessons.length) return;
    const reordered = [...modules];
    const lessons = [...reordered[modIdx].lessons];
    [lessons[lessonIdx], lessons[newIdx]] = [lessons[newIdx], lessons[lessonIdx]];
    reordered[modIdx] = { ...reordered[modIdx], lessons };
    setModules(reordered);
    if (latestTokenRef.current && isCurrent()) {
      try {
        const response = await fetch(`${API_URL}/v1/lessons/${moduleId}/reorder`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
          body: JSON.stringify(lessons.map((l) => l.id)),
        });
        if (!response.ok) throw new Error('Lesson reorder failed');
      } catch {
        if (!isCurrent()) return;
        setModules(modules);
        toast.error(t('authenticatedUi.editor.reorderFailed'));
      }
    }
  };

  const handleEditLessonContent = useCallback(async (lessonId: string) => {
    if (!latestTokenRef.current || correctionBusyRef.current) return;
    const captured = { ...scopeRef.current };
    if (captured.identity !== workspaceScope || !isScopeCurrent(captured)) return;
    setLoadingLessonId(lessonId);
    try {
      const res = await authorRead(`${API_URL}/v1/lessons/${lessonId}`, captured.identity.session);
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.message || payload?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!isScopeCurrent(captured)) return;
      if (editorSnapshot.current.editingLessonId && editorSnapshot.current.editingLessonId !== lessonId) {
        // The old opaque plan belongs to the previous selected lesson. Clear it
        // before the new panel mounts, without touching other query/hash state.
        const url = new URL(window.location.href);
        url.searchParams.delete('correction_plan');
        window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
      }
      setEditingLessonId(lessonId);
      setEditLessonTitle(data.title || '');
      setEditLessonContent(data.content || '');
      setSavedLessonTitle(data.title || '');
      setSavedLessonContent(data.content || '');
      setLessonView('edit');
    } catch (error) {
      if (isScopeCurrent(captured)) toast.error(t('authenticatedUi.editor.openLessonFailed'), { description: (error as Error).message });
    } finally {
      if (isScopeCurrent(captured)) setLoadingLessonId(null);
    }
  }, [API_URL, t, workspaceScope, isScopeCurrent]);

  useEffect(() => {
    const lessonId = new URLSearchParams(window.location.search).get('lessonId');
    const key = `${courseId}:${lessonId}`;
    if (!lessonId || course?.id !== courseId || readinessUnavailable || initialLessonRef.current === key || !modules.some((module) => module.lessons.some((lesson) => lesson.id === lessonId))) return;
    initialLessonRef.current = key;
    void handleEditLessonContent(lessonId);
  }, [courseId, course?.id, readinessUnavailable, modules, handleEditLessonContent]);

  const handleSaveLessonContent = async () => {
    if (!editingLessonId || !token || !editLessonTitle.trim() || correctionBusyRef.current) return;
    const captured = { ...scopeRef.current };
    if (captured.identity !== workspaceScope || !isScopeCurrent(captured)) return;
    const saveGeneration = ++saveGenerationRef.current;
    const isCurrentSave = () => isScopeCurrent(captured) && saveGeneration === saveGenerationRef.current;
    setSavingLesson(true);
    try {
      const res = await fetch(`${API_URL}/v1/lessons/${editingLessonId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${latestTokenRef.current}` },
        body: JSON.stringify({
          title: editLessonTitle.trim(),
          content: editLessonContent,
        }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.message || payload?.detail || `HTTP ${res.status}`);
      }
      if (!isCurrentSave()) return;
      setModules((prev) =>
        prev.map((module) => ({
          ...module,
          lessons: module.lessons.map((lesson) =>
            lesson.id === editingLessonId
              ? { ...lesson, title: editLessonTitle.trim() }
              : lesson
          ),
        }))
      );
      toast.success(t('authenticatedUi.editor.lessonSaved'));
      setEditLessonTitle(editLessonTitle.trim());
      setSavedLessonTitle(editLessonTitle.trim());
      setSavedLessonContent(editLessonContent);
      // Do not present a pre-edit review status as approval of the new version.
      const metadataGeneration = ++metadataGenerationRef.current;
      const isCurrentRead = () => isCurrentSave() && metadataGeneration === metadataGenerationRef.current;
      setReadinessUnavailable(true);
      try {
        const reviewResponse = await authorRead(`${API_URL}/v1/courses/${courseId}`, captured.identity.session);
        if (!reviewResponse.ok) throw new Error('Review status readback failed');
        const reviewedCourse = await reviewResponse.json() as Course;
        if (!isCurrentRead()) return;
        if (reviewedCourse.id !== captured.identity.courseId) throw new Error('Course identity mismatch');
        setCourse(reviewedCourse);
        setReadinessUnavailable(false);
        setLoadError(false);
      } catch {
        // The lesson was saved; a failed status read must not relabel it unsaved.
        if (isCurrentRead()) setLoadError(true);
      }
    } catch (error) {
      if (isCurrentSave()) toast.error(t('authenticatedUi.editor.saveLessonFailed'), { description: (error as Error).message });
    } finally {
      if (isCurrentSave()) setSavingLesson(false);
    }
  };

  const handleSelectLesson = async (lessonId: string) => {
    if (correctionBusyRef.current) return;
    if (lessonId === editingLessonId) return;
    if (lessonDirty) {
      const discard = await confirm({
        title: t('authenticatedUi.editor.unsavedTitle'),
        message: t('authenticatedUi.editor.unsavedDescription'),
        confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
        variant: 'danger',
      });
      if (!discard) return;
    }
    await handleEditLessonContent(lessonId);
  };

  const handleSelectLessonReload = async () => {
    if (!editingLessonId || correctionBusyRef.current) return;
    if (lessonDirty) {
      const discard = await confirm({
        title: t('authenticatedUi.editor.unsavedTitle'),
        message: t('authenticatedUi.editor.unsavedDescription'),
        confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
        variant: 'danger',
      });
      if (!discard) return;
    }
    await handleEditLessonContent(editingLessonId);
  };

  const handleDiscardLessonChanges = async () => {
    if (correctionBusyRef.current) return;
    if (!lessonDirty) return;
    const discard = await confirm({
      title: t('authenticatedUi.editor.unsavedTitle'),
      message: t('authenticatedUi.editor.unsavedDescription'),
      confirmLabel: t('authenticatedUi.editor.discard'),
      variant: 'danger',
    });
    if (!discard) return;
    setEditLessonTitle(savedLessonTitle);
    setEditLessonContent(savedLessonContent);
  };

  const handleOpenLearnerPreview = async () => {
    if (correctionBusyRef.current) return;
    if (!activeLesson) return;
    if (workspaceDirty) {
      const discard = await confirm({
        title: t('authenticatedUi.editor.unsavedTitle'),
        message: t('authenticatedUi.editor.unsavedDescription'),
        confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
        variant: 'danger',
      });
      if (!discard) return;
    }
    router.push(`/courses/${courseId}?lessonId=${encodeURIComponent(activeLesson.id)}`);
  };

  const handleGuardedLink = async (event: ReactMouseEvent<HTMLAnchorElement>, href: string) => {
    if (correctionBusyRef.current) { event.preventDefault(); return; }
    if (!workspaceDirty) return;
    event.preventDefault();
    const discard = await confirm({
      title: t('authenticatedUi.editor.unsavedTitle'),
      message: t('authenticatedUi.editor.unsavedDescription'),
      confirmLabel: t('authenticatedUi.editor.leaveWithoutSaving'),
      variant: 'danger',
    });
    if (discard) router.push(href);
  };

  const releaseRequest = async (path: string, body?: object) => {
    if (!latestTokenRef.current) return null;
    const response = await fetch(`${API_URL}/v1/courses/${courseId}/${path}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${latestTokenRef.current}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(
        coursePublicationError(payload, t)
        || payload?.message
        || payload?.details?.message
        || payload?.detail?.message
        || payload?.detail
        || t('authenticatedUi.editor.statusChangeFailed'),
      );
    }
    return response.json() as Promise<Course>;
  };

  const handleApprove = async () => {
    const isCurrent = beginAction('release');
    if (!isCurrent()) return;
    setReleaseAction('approve');
    try {
      const updated = await releaseRequest('review', { review_status: 'approved' });
      if (!isCurrent()) return;
      if (updated) setCourse(updated);
      toast.success(t('authenticatedUi.editor.courseApproved'), { description: t('authenticatedUi.editor.courseApprovedHint') });
    } catch (error) {
      if (isCurrent()) toast.error(t('authenticatedUi.editor.approveFailed'), { description: (error as Error).message });
    } finally {
      if (isCurrent()) setReleaseAction(null);
    }
  };

  const handlePublish = async () => {
    const isCurrent = beginAction('release');
    if (!isCurrent()) return;
    setReleaseAction('publish');
    try {
      const updated = await releaseRequest('publish');
      if (!isCurrent()) return;
      if (updated) setCourse(updated);
      toast.success(
        course?.source_instruction_id ? t('authenticatedUi.editor.publishedAssigned') : t('authenticatedUi.editor.published'),
        course?.source_instruction_id
          ? { description: t('authenticatedUi.editor.assignmentActivated') }
          : undefined,
      );
    } catch (error) {
      if (isCurrent()) toast.error(t('authenticatedUi.editor.publishFailed'), { description: (error as Error).message });
    } finally {
      if (isCurrent()) setReleaseAction(null);
    }
  };

  if (loading || dataScopeRef.current !== workspaceScope) return <WorkspacePage id="course-editor"><div role="status" className="rounded-2xl border border-border bg-card p-6">{t('common.loading')}</div></WorkspacePage>;
  if (!course) return <WorkspacePage id="course-editor"><div role="alert" className="space-y-3 rounded-2xl border border-border bg-card p-6"><p>{copy.loadFailed}</p><Button onClick={() => void fetchData()}>{copy.retry}</Button></div></WorkspacePage>;

  const hasBlueprintMarker = Boolean(course.source_analysis?.blueprint && Object.keys(course.source_analysis.blueprint).length > 0);
  const approvedSources = sourceReviewPins(course.source_analysis?.source_editorial_snapshots);
  const missingAssets = course.source_analysis?.unplaced_source_assets;
  const unplacedCount = Array.isArray(missingAssets)
    ? new Set(missingAssets.filter((id): id is string => typeof id === 'string' && /^asset-[a-f0-9]{64}$/.test(id))).size : 0;
  const sourceCopy = sourceReviewCopy(lang);
  const requiresCourseReview = course.ai_generated || hasBlueprintMarker;
  const published = course.status === 'published';
  const approved = course.review_status === 'approved';
  const courseQuery = encodeURIComponent(course.id);
  const nextAfterPublication = programGenerationJob
    ? `/ai/generate?job_id=${encodeURIComponent(programGenerationJob)}`
    : `/assignments?courseId=${courseQuery}`;
  const nextActionLabel = programGenerationJob ? t('ai.programAttach.attach') : t('releaseSteps.assign');
  const approvalButton = (
    <Button type="button" size="sm" variant="outline" onClick={handleApprove} disabled={releaseAction !== null || workspaceDirty || readinessUnavailable}>
      <CheckCircle2 className="mr-1.5 h-4 w-4" />
      {releaseAction === 'approve' ? t('authenticatedUi.editor.approving') : t('authenticatedUi.editor.approveCourse')}
    </Button>
  );
  const publicationButton = (
    <Button type="button" size="sm" onClick={handlePublish} disabled={releaseAction !== null || workspaceDirty || readinessUnavailable}>
      <Rocket className="mr-1.5 h-4 w-4" />
      {releaseAction === 'publish' ? t('authenticatedUi.editor.publishing') : course.source_instruction_id
        ? t('authenticatedUi.editor.publishAndAssign') : t('authenticatedUi.editor.publish')}
    </Button>
  );
  const workflowLinkClass = 'inline-flex min-h-10 items-center rounded-md px-2 text-sm font-medium text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring';

  return (
    <WorkspacePage id="course-editor" className="mx-auto max-w-[1800px]">
      <fieldset
        disabled={correctionBusy || loadingLessonId !== null || savingLesson || releaseAction !== null}
        aria-label={t('courses.editCourse')}
        className="min-w-0 space-y-6 border-0 p-0"
      >
      <WorkspacePageHeader title={t('courses.editCourse')} icon={<Pencil />} eyebrow={
          <a
            href={`/courses/${courseId}`}
            onClick={(event) => void handleGuardedLink(event, `/courses/${courseId}`)}
            className="flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ChevronLeft className="w-4 h-4" /> {course.title}
          </a>
      } description={
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant={course.status === 'published' ? 'default' : 'outline'}>
              {course.status === 'published' ? t('courses.published') : t('courses.draft')}
            </Badge>
            {course.ai_generated && (
              <Badge variant={course.review_status === 'approved' ? 'secondary' : 'outline'}>
                {readinessUnavailable ? copy.unavailable : course.review_status === 'approved' ? t('authenticatedUi.editor.reviewed') : t('authenticatedUi.editor.needsReview')}
              </Badge>
            )}
            {course.source_instruction_id && <Badge variant="outline">{t('authenticatedUi.editor.byJobInstruction')}</Badge>}
          </div>
      } actions={
        <div className="flex max-w-full flex-wrap gap-2 sm:justify-end lg:max-w-[620px] [&_button]:h-auto [&_button]:min-h-10 [&_button]:whitespace-normal">
          {!course.ai_generated && !published && requiresCourseReview && !approved && approvalButton}
          {!course.ai_generated && !published && (!requiresCourseReview || approved) && publicationButton}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setChatFocus({});
              setChatOpen(true);
            }}
          >
            <Sparkles className="w-4 h-4 mr-1" />
            {t('authenticatedUi.editor.assistant')}
          </Button>
          <Link
            href={`/admin/course-approvals?courseId=${encodeURIComponent(course.id)}`}
            onClick={(event) => void handleGuardedLink(
              event,
              `/admin/course-approvals?courseId=${encodeURIComponent(course.id)}`,
            )}
            className="inline-flex min-h-10 items-center justify-center rounded-md border border-input px-3 py-2 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('authenticatedUi.editor.approval')}
          </Link>
        </div>
      } />
      {loadError && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/40 p-4 text-sm"><p>{copy.loadFailed}</p><Button variant="outline" size="sm" onClick={() => void fetchData()}>{copy.retry}</Button></div>}
      {workspaceDirty && <p role="status" className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-sm">{copy.unsaved}</p>}
      {course.ai_generated && <SourceReviewPanel key={`${course.id}:${session.generation}`}
        courseId={course.id} lang={lang} disabled={readinessUnavailable || workspaceDirty || Boolean(releaseAction)}
        onResolved={() => { void fetchData(); }} />}
      <details data-publication-checks className="rounded-xl border border-border bg-card">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
        {copy.publicationChecks}
        <span className="font-normal text-muted-foreground">· {readinessUnavailable ? copy.unavailable : published ? t('courses.published') : workspaceDirty ? copy.changes : !requiresCourseReview ? copy.notRequired : approved ? copy.approved : course.review_status === 'needs_changes' ? copy.needsChanges : copy.pending}</span>
      </summary>
      <div className="space-y-4 border-t border-border p-4">
      {course.ai_generated && (
        <section id="course-release" aria-labelledby="course-release-heading" className="scroll-mt-24 rounded-xl border border-border bg-card p-4 sm:p-5">
          <h2 id="course-release-heading" className="font-semibold">{t('releaseSteps.title')}</h2>
          <ol className="mt-3 list-decimal space-y-3 pl-5 text-sm marker:font-semibold">
            <li>
              <p className="mb-2 pl-2 font-medium">{t('releaseSteps.source')}</p>
            </li>
            <li>
              <Link className={workflowLinkClass} href={`/quizzes?courseId=${courseQuery}${programGenerationJob ? `&programGenerationJob=${encodeURIComponent(programGenerationJob)}` : ''}`}>{t('releaseSteps.quizzes')}</Link>
              {!published && <p className="px-2 text-muted-foreground">{t('releaseSteps.quizzesHint')}</p>}
            </li>
            <li className="pl-2">
              {approved || published
                ? <span className="font-medium">{t('releaseSteps.approve')} · {t('releaseSteps.done')}</span>
                : approvalButton}
            </li>
            <li className="pl-2">
              {published
                ? <span className="font-medium">{t('releaseSteps.publish')} · {t('releaseSteps.done')}</span>
                : approved ? publicationButton : <span>{t('releaseSteps.publish')} · {t('releaseSteps.afterApproval')}</span>}
              {!published && <p className="mt-1 text-muted-foreground">{t('releaseSteps.approvalHint')}</p>}
            </li>
            {!course.source_instruction_id && <li>
              {published
                ? <Link className={workflowLinkClass} href={nextAfterPublication}>{nextActionLabel}</Link>
                : <span className="pl-2">{nextActionLabel} · {t('releaseSteps.afterPublication')}</span>}
            </li>}
          </ol>
        </section>
      )}
      <ApprovalPolicyCard courseId={course.id} initialRequiresApproval={Boolean(course.requires_approval)} />
      <CourseReadiness lang={lang} moduleCount={modules.length} lessonCount={lessonSequence.length} dirty={workspaceDirty}
        requiresReview={requiresCourseReview} reviewStatus={course.review_status} unavailable={readinessUnavailable} />
      <WorkspaceToolbar className="py-2">
      <nav aria-label={copy.readiness} className="flex flex-wrap gap-x-6 gap-y-2 text-sm font-medium text-primary">
        <Link
          className="inline-flex min-h-10 items-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          href={`/admin/course-approvals?courseId=${encodeURIComponent(course.id)}`}
          onClick={(event) => void handleGuardedLink(
            event,
            `/admin/course-approvals?courseId=${encodeURIComponent(course.id)}`,
          )}
        >{copy.approvalLink}</Link>
        {!course.ai_generated && <Link className="inline-flex min-h-10 items-center" href={`/quizzes?courseId=${courseQuery}`}>{copy.quizzesLink}</Link>}
      </nav>
      </WorkspaceToolbar>
      </div>
      </details>
      {(approvedSources.length > 0 || (unplacedCount > 0 && !published)) && <section className="space-y-2 rounded-xl border border-border p-4" aria-label={sourceCopy.status}>
        <h2 className="text-sm font-semibold">{sourceCopy.status}</h2>
        {unplacedCount > 0 && !published && <p className="text-sm" role="status">{copy.unplacedIllustrations.replace('{count}', String(unplacedCount))}</p>}
        <ul className="space-y-1">{approvedSources.map((source, index) => <li key={source.approval_id}>
          <Link className="text-sm text-primary underline" href={sourceReviewHref(source.document_id, source.approval_id)}>
            {sourceCopy.preview} {approvedSources.length > 1 ? index + 1 : ''} · {sourceCopy.revision} {source.revision}
          </Link>
        </li>)}</ul>
      </section>}
      {course.status !== 'published' && course.source_instruction_id && (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">
          {t('authenticatedUi.editor.draftVisibilityHint')}
        </div>
      )}

      <div data-authoring-workspace className="grid min-h-[680px] min-w-0 grid-cols-1 items-start gap-5 xl:grid-cols-[280px_minmax(0,1fr)] 2xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)_280px]">
        <Card className="min-h-0 min-w-0 overflow-hidden xl:sticky xl:top-4 xl:h-[calc(100dvh-2rem)]">
          <CardContent className="flex h-full min-h-0 flex-col gap-4 p-4">
            <div className="-mx-4 -mt-4 flex items-center gap-2 border-b border-border bg-muted/20 px-4 py-4">
              <ListTree className="h-5 w-5 text-primary" aria-hidden="true" />
              <h2 className="font-semibold">{t('authenticatedUi.editor.outline')}</h2>
            </div>
            <div className="flex min-w-0 flex-wrap gap-2">
              <Input
                className="min-w-0 flex-1 basis-32"
                aria-label={t('courses.addModule')}
                placeholder={t('courses.addModule') + '...'}
                value={newModuleTitle}
                disabled={creationBusy}
                aria-invalid={creationError?.target === 'module' || undefined}
                aria-describedby={creationError?.target === 'module' ? 'module-create-error' : undefined}
                onChange={(event) => setNewModuleTitle(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && handleAddModule()}
              />
              <Button size="sm" onClick={handleAddModule} disabled={creationBusy || !newModuleTitle.trim()}>
                {t('common.create')}
              </Button>
            </div>
            {creationError?.target === 'module' && <p id="module-create-error" role="alert" className="text-sm text-destructive">{creationError.message}</p>}
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
              {modules.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">{t('courses.noModules')}</p>
              ) : modules.map((mod, modIdx) => (
                <section key={mod.id} aria-labelledby={`module-${mod.id}`} className="space-y-2 rounded-lg border border-border/70 p-2">
                  {editingModuleId === mod.id ? (
                    <div className="space-y-2">
                      <Input aria-label={t('courses.moduleTitle')} value={editModuleTitle} onChange={(event) => setEditModuleTitle(event.target.value)} autoFocus onKeyDown={(event) => event.key === 'Enter' && handleUpdateModule(mod.id)} />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => handleUpdateModule(mod.id)}>{t('common.save')}</Button>
                        <Button variant="outline" size="sm" onClick={() => setEditingModuleId(null)}>{t('common.cancel')}</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-1">
                      <div className="flex flex-col gap-0.5">
                        <Button aria-label={t('authenticatedUi.editor.moveModuleUp')} variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => handleMoveModule(mod.id, 'up')} disabled={modIdx === 0}><ChevronUp className="h-4 w-4" aria-hidden="true" /></Button>
                        <Button aria-label={t('authenticatedUi.editor.moveModuleDown')} variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => handleMoveModule(mod.id, 'down')} disabled={modIdx === modules.length - 1}><ChevronDown className="h-4 w-4" aria-hidden="true" /></Button>
                      </div>
                      <h3 id={`module-${mod.id}`} className="min-w-0 flex-1 py-1 text-sm font-semibold leading-5">{mod.title}</h3>
                      <Button aria-label={t('common.edit')} variant="ghost" size="sm" className="h-8 px-2" onClick={() => void handleEditModule(mod)}><Pencil className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                      <Button aria-label={t('common.delete')} variant="ghost" size="sm" className="h-8 px-2 text-destructive" onClick={() => handleDeleteModule(mod.id)}><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                    </div>
                  )}
                  <div className="space-y-1">
                    {mod.lessons.map((lesson, lessonIdx) => (
                      <div key={lesson.id} className={`group flex items-center gap-1 rounded-md border ${editingLessonId === lesson.id ? 'border-primary bg-primary/10' : 'border-transparent hover:border-border hover:bg-muted/60'}`}>
                        <div className="flex flex-col">
                          <Button aria-label={t('authenticatedUi.editor.moveLessonUp')} variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => handleMoveLesson(lesson.id, mod.id, 'up')} disabled={lessonIdx === 0}><ChevronUp className="h-4 w-4" aria-hidden="true" /></Button>
                          <Button aria-label={t('authenticatedUi.editor.moveLessonDown')} variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => handleMoveLesson(lesson.id, mod.id, 'down')} disabled={lessonIdx === mod.lessons.length - 1}><ChevronDown className="h-4 w-4" aria-hidden="true" /></Button>
                        </div>
                        <button
                          type="button"
                          aria-current={editingLessonId === lesson.id ? 'true' : undefined}
                          className="flex min-w-0 flex-1 items-center gap-2 px-1 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          disabled={loadingLessonId !== null}
                          onClick={() => void handleSelectLesson(lesson.id)}
                        >
                          {loadingLessonId === lesson.id ? <LoaderCircle className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" /> : <FileText className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
                          <span className="truncate">{lesson.title}</span>
                        </button>
                        <Button aria-label={t('authenticatedUi.editor.deleteLesson', { title: lesson.title })} variant="ghost" size="sm" className="h-8 px-2 text-destructive opacity-70 group-hover:opacity-100" onClick={() => handleDeleteLesson(lesson.id, mod.id)}><X className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                      </div>
                    ))}
                  </div>
                  {addingLessonToModule === mod.id ? (
                    <div className="space-y-2 pt-1">
                      <Input aria-label={t('courses.addLesson')} placeholder={t('courses.addLesson') + '...'} value={newLessonTitle} disabled={creationBusy} aria-invalid={creationError?.target === mod.id || undefined} aria-describedby={creationError?.target === mod.id ? `lesson-create-error-${mod.id}` : undefined} onChange={(event) => setNewLessonTitle(event.target.value)} autoFocus onKeyDown={(event) => event.key === 'Enter' && handleAddLesson(mod.id)} />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={creationBusy || !newLessonTitle.trim()} onClick={() => handleAddLesson(mod.id)}>{t('common.create')}</Button>
                        <Button variant="outline" size="sm" disabled={creationBusy} onClick={() => { setAddingLessonToModule(null); setNewLessonTitle(''); setCreationError(null); }}>{t('common.cancel')}</Button>
                      </div>
                      {creationError?.target === mod.id && <p id={`lesson-create-error-${mod.id}`} role="alert" className="text-sm text-destructive">{creationError.message}</p>}
                    </div>
                  ) : (
                    <Button variant="ghost" size="sm" className="w-full justify-start text-primary" onClick={() => setAddingLessonToModule(mod.id)}>+ {t('courses.addLesson')}</Button>
                  )}
                </section>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden rounded-2xl">
          <CardContent className="flex min-h-[680px] flex-col p-0">
            {editingLessonId && activeLesson ? (
              <>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-border p-4">
                  <div className="min-w-0 flex-1 basis-48">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t('authenticatedUi.editor.workspaceTitle')}</p>
                    <p className="truncate text-sm text-muted-foreground"><span>{activeModule?.title}</span> · <span>{activeLesson.title}</span></p>
                  </div>
                  <div className="flex min-w-0 max-w-full flex-wrap rounded-md border border-border p-1" role="group" aria-label={t('authenticatedUi.editor.viewMode')}>
                    <Button type="button" size="sm" aria-pressed={lessonView === 'edit'} variant={lessonView === 'edit' ? 'secondary' : 'ghost'} onClick={() => setLessonView('edit')}><Pencil className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('authenticatedUi.editor.editMode')}</Button>
                    <Button type="button" size="sm" aria-pressed={lessonView === 'preview'} variant={lessonView === 'preview' ? 'secondary' : 'ghost'} onClick={() => setLessonView('preview')}><Eye className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('authenticatedUi.editor.previewMode')}</Button>
                  </div>
                </div>
                {lessonView === 'edit' ? (
                  <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 sm:p-6">
                    <label className="block space-y-2">
                      <span className="text-sm font-medium">{t('authenticatedUi.editor.lessonTitle')}</span>
                      <Input value={editLessonTitle} onChange={(event) => setEditLessonTitle(event.target.value)} name="lesson-title" autoComplete="off" placeholder={t('authenticatedUi.editor.lessonTitlePlaceholder')} />
                    </label>
                    <div className="flex min-h-0 flex-1 flex-col gap-2">
                      <label htmlFor="author-lesson-content" className="text-sm font-medium">{t('authenticatedUi.editor.lessonContent')}</label>
                      <MarkdownToolbar value={editLessonContent} onChange={setEditLessonContent} textareaRef={lessonTextareaRef} lang={lang} />
                      <textarea
                        id="author-lesson-content"
                        ref={lessonTextareaRef}
                        value={editLessonContent}
                        onChange={(event) => setEditLessonContent(event.target.value)}
                        name="lesson-content"
                        autoComplete="off"
                        className="min-h-[500px] w-full flex-1 resize-y rounded-md border border-input bg-background px-4 py-3 text-base leading-7 outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20"
                        placeholder={t('authenticatedUi.editor.lessonContentPlaceholder')}
                      />
                    </div>
                  </div>
                ) : (
                  <article className="min-h-[560px] overflow-x-auto p-6 sm:p-10">
                    <h1 className="mb-8 text-3xl font-bold tracking-tight">{editLessonTitle || t('authenticatedUi.editor.lessonTitle')}</h1>
                    <LessonContent
                      text={editLessonContent}
                      omitFirstHeading={editLessonTitle}
                      className="space-y-5 text-base leading-7 text-foreground [&_blockquote]:border-l-4 [&_blockquote]:border-primary/40 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_h1]:text-3xl [&_h1]:font-bold [&_h2]:mt-8 [&_h2]:text-2xl [&_h2]:font-semibold [&_h3]:mt-6 [&_h3]:text-xl [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:p-2 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-2 [&_th]:text-left [&_ul]:list-disc"
                    />
                  </article>
                )}
                <div className="sticky bottom-0 z-10 flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-border bg-card p-4 shadow-sm">
                  <p role="status" className={`text-sm ${lessonDirty ? 'text-warning' : 'text-muted-foreground'}`}>
                    {savingLesson ? t('common.saving') : lessonDirty ? t('authenticatedUi.editor.unsavedChanges') : t('common.saved')}
                  </p>
                  <div className="flex min-w-0 max-w-full flex-wrap gap-2">
                    <Button className="h-auto min-h-10 whitespace-normal" variant="outline" onClick={() => void handleDiscardLessonChanges()} disabled={!lessonDirty || savingLesson}>{t('authenticatedUi.editor.discard')}</Button>
                    <Button className="h-auto min-h-10 whitespace-normal" onClick={handleSaveLessonContent} disabled={!lessonDirty || savingLesson || !editLessonTitle.trim()}>
                      {savingLesson && <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />}
                      {savingLesson ? t('common.saving') : t('common.save')}
                    </Button>
                  </div>
                </div>
                <nav aria-label={copy.context} className="flex flex-wrap items-center justify-between gap-2 border-t border-border p-4">
                  <Button variant="ghost" size="sm" disabled={activeLessonIndex <= 0} onClick={() => void handleSelectLesson(lessonSequence[activeLessonIndex - 1].id)}>{copy.previous}</Button>
                  <Link className="inline-flex min-h-10 items-center text-sm font-medium text-primary" href={`/quizzes?lessonId=${encodeURIComponent(activeLesson.id)}`}>{copy.lessonQuiz}</Link>
                  <Button variant="ghost" size="sm" disabled={activeLessonIndex < 0 || activeLessonIndex >= lessonSequence.length - 1} onClick={() => void handleSelectLesson(lessonSequence[activeLessonIndex + 1].id)}>{copy.next}</Button>
                </nav>
              </>
            ) : (
              <div className="flex min-h-[680px] flex-col items-center justify-center gap-3 p-8 text-center">
                <FileText className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
                <h2 className="text-lg font-semibold">{t('authenticatedUi.editor.emptySelection')}</h2>
                <p className="max-w-md text-sm text-muted-foreground">{t('authenticatedUi.editor.selectLesson')}</p>
              </div>
            )}
          </CardContent>
        </Card>

        <aside className="min-w-0 space-y-4 xl:col-span-2 2xl:sticky 2xl:top-4 2xl:col-span-1">
          <Card className="rounded-2xl">
            <CardContent className="space-y-4 p-4">
              <h2 className="font-semibold">{t('authenticatedUi.editor.lessonProperties')}</h2>
              {activeLesson ? (
                <>
                  <div className="space-y-1 text-sm">
                    <p className="text-muted-foreground">{t('authenticatedUi.editor.contentType')}</p>
                    <Badge variant="outline">{activeLesson.content_type}</Badge>
                  </div>
                  <Button
                    variant="outline"
                    className="w-full justify-start"
                    onClick={() => {
                      setChatFocus({ lessonId: activeLesson.id, lessonTitle: editLessonTitle || activeLesson.title });
                      setChatOpen(true);
                    }}
                  >
                    <Bot className="mr-2 h-4 w-4" aria-hidden="true" />
                    {t('authenticatedUi.editor.lessonAssistantTitle')}
                  </Button>
                  <button
                    type="button"
                    onClick={handleOpenLearnerPreview}
                    className="inline-flex min-h-10 w-full items-center justify-center rounded-md border border-input px-3 py-2 text-sm font-medium hover:bg-muted"
                  >
                    <Eye className="mr-2 h-4 w-4" aria-hidden="true" />
                    {t('authenticatedUi.editor.learnerPreview')}
                  </button>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">{t('authenticatedUi.editor.selectLesson')}</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
      </fieldset>
      {course.status === 'draft' && activeLesson?.content_type === 'text' && editingLessonId && (
        <LessonCorrectionPanel ref={correctionPanelRef} courseId={courseId} lessonId={editingLessonId} lessonTitle={savedLessonTitle}
          savedContent={savedLessonContent} dirty={lessonDirty} editorBusy={savingLesson || loadingLessonId !== null || releaseAction !== null}
          onApplied={onCorrectionApplied} onApplyingChange={onCorrectionApplyingChange}
          onReload={() => void handleSelectLessonReload()} />
      )}
      {dialog}

      <AIChatPanel
        open={chatOpen && !correctionBusy}
        onClose={() => setChatOpen(false)}
        courseId={courseId}
        focusLessonId={chatFocus.lessonId}
        focusLessonTitle={chatFocus.lessonTitle}
        focusModuleId={chatFocus.moduleId}
        focusModuleTitle={chatFocus.moduleTitle}
        onLessonApplied={() => fetchData()}
        onReviewLessonSuggestion={(lessonId, instruction) => {
          if (course.status !== 'draft' || activeLesson?.content_type !== 'text' || activeLesson.id !== lessonId
            || editingLessonId !== lessonId || chatFocus.lessonId !== lessonId || correctionBusyRef.current
            || lessonDirty || savingLesson || loadingLessonId || releaseAction) return false;
          return correctionPanelRef.current?.stageInstruction({ lessonId, instruction, locale: lang }) ?? false;
        }}
      />
    </WorkspacePage>
  );
}
