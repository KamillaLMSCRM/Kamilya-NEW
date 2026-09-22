'use client';

import Link from 'next/link';

import { useState, useEffect, useCallback, useMemo, type MouseEvent as ReactMouseEvent } from 'react';
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
}

export default function CourseEditPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params?.id as string;
  const { t } = useT();
  const { confirm, dialog } = useConfirm();
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
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
  const [savingLesson, setSavingLesson] = useState(false);
  const [releaseAction, setReleaseAction] = useState<'approve' | 'publish' | null>(null);

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
  const lessonDirty = Boolean(editingLessonId)
    && (editLessonTitle !== savedLessonTitle || editLessonContent !== savedLessonContent);

  useEffect(() => {
    if (!lessonDirty) return;
    const guardUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', guardUnload);
    return () => window.removeEventListener('beforeunload', guardUnload);
  }, [lessonDirty]);

  useEffect(() => {
    if (!lessonDirty) return;

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
  }, [confirm, lessonDirty, router, t]);

  const fetchData = useCallback(async () => {
    if (!courseId || !token) return;
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [courseRes, structRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses/${courseId}`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/structure`, { headers }),
      ]);
      if (courseRes.ok) setCourse(await courseRes.json());
      if (structRes.ok) {
        const data = await structRes.json();
        setModules(data.modules || []);
      }
    } finally {
      setLoading(false);
    }
  }, [courseId, token, API_URL]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleAddModule = async () => {
    if (!newModuleTitle.trim() || !token) return;
    const res = await fetch(`${API_URL}/v1/courses/${courseId}/modules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ title: newModuleTitle }),
    });
    if (res.ok) {
      const mod = await res.json();
      setModules((prev) => [...prev, { ...mod, lessons: [] }]);
      setNewModuleTitle('');
    }
  };

  const handleUpdateModule = async (moduleId: string) => {
    if (!editModuleTitle.trim() || !token) return;
    await fetch(`${API_URL}/v1/modules/${moduleId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ title: editModuleTitle }),
    });
    setModules((prev) => prev.map((m) => m.id === moduleId ? { ...m, title: editModuleTitle } : m));
    setEditingModuleId(null);
  };

  const handleDeleteModule = async (moduleId: string) => {
    if (!token) return;
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
    if (!ok) return;
    await fetch(`${API_URL}/v1/modules/${moduleId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setModules((prev) => prev.filter((m) => m.id !== moduleId));
    if (removesActiveLesson) setEditingLessonId(null);
  };

  const handleAddLesson = async (moduleId: string) => {
    if (!newLessonTitle.trim() || !token) return;
    const res = await fetch(`${API_URL}/v1/modules/${moduleId}/lessons`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ title: newLessonTitle, content_type: 'text' }),
    });
    if (res.ok) {
      const lesson = await res.json();
      setModules((prev) => prev.map((m) =>
        m.id === moduleId ? { ...m, lessons: [...m.lessons, lesson] } : m
      ));
      setNewLessonTitle('');
      setAddingLessonToModule(null);
    }
  };

  const handleDeleteLesson = async (lessonId: string, moduleId: string) => {
    if (!token) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteLesson'),
      message: editingLessonId === lessonId && lessonDirty
        ? t('authenticatedUi.editor.unsavedDescription')
        : undefined,
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    await fetch(`${API_URL}/v1/lessons/${lessonId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setModules((prev) => prev.map((m) =>
      m.id === moduleId ? { ...m, lessons: m.lessons.filter((l) => l.id !== lessonId) } : m
    ));
    if (editingLessonId === lessonId) setEditingLessonId(null);
  };

  const handleMoveModule = async (moduleId: string, direction: 'up' | 'down') => {
    const idx = modules.findIndex((m) => m.id === moduleId);
    if (idx < 0) return;
    const newIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (newIdx < 0 || newIdx >= modules.length) return;
    const reordered = [...modules];
    [reordered[idx], reordered[newIdx]] = [reordered[newIdx], reordered[idx]];
    setModules(reordered);
    // Persist reorder
    if (token) {
      await fetch(`${API_URL}/v1/courses/${courseId}/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(reordered.map((m) => m.id)),
      });
    }
  };

  const handleMoveLesson = async (lessonId: string, moduleId: string, direction: 'up' | 'down') => {
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
    if (token) {
      try {
        const response = await fetch(`${API_URL}/v1/lessons/${moduleId}/reorder`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(lessons.map((l) => l.id)),
        });
        if (!response.ok) throw new Error('Lesson reorder failed');
      } catch {
        setModules(modules);
        toast.error(t('authenticatedUi.editor.reorderFailed'));
      }
    }
  };

  const handleEditLessonContent = async (lessonId: string) => {
    if (!token) return;
    setLoadingLessonId(lessonId);
    try {
      const res = await fetch(`${API_URL}/v1/lessons/${lessonId}`, {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.message || payload?.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setEditingLessonId(lessonId);
      setEditLessonTitle(data.title || '');
      setEditLessonContent(data.content || '');
      setSavedLessonTitle(data.title || '');
      setSavedLessonContent(data.content || '');
      setLessonView('edit');
    } catch (error) {
      toast.error(t('authenticatedUi.editor.openLessonFailed'), { description: (error as Error).message });
    } finally {
      setLoadingLessonId(null);
    }
  };

  const handleSaveLessonContent = async () => {
    if (!editingLessonId || !token || !editLessonTitle.trim()) return;
    setSavingLesson(true);
    try {
      const res = await fetch(`${API_URL}/v1/lessons/${editingLessonId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          title: editLessonTitle.trim(),
          content: editLessonContent,
        }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        throw new Error(payload?.message || payload?.detail || `HTTP ${res.status}`);
      }
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
    } catch (error) {
      toast.error(t('authenticatedUi.editor.saveLessonFailed'), { description: (error as Error).message });
    } finally {
      setSavingLesson(false);
    }
  };

  const handleSelectLesson = async (lessonId: string) => {
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

  const handleDiscardLessonChanges = async () => {
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
    if (!activeLesson) return;
    if (lessonDirty) {
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
    if (!lessonDirty) return;
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
    if (!token) return null;
    const response = await fetch(`${API_URL}/v1/courses/${courseId}/${path}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
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
    setReleaseAction('approve');
    try {
      const updated = await releaseRequest('review', { review_status: 'approved' });
      if (updated) setCourse(updated);
      toast.success(t('authenticatedUi.editor.courseApproved'), { description: t('authenticatedUi.editor.courseApprovedHint') });
    } catch (error) {
      toast.error(t('authenticatedUi.editor.approveFailed'), { description: (error as Error).message });
    } finally {
      setReleaseAction(null);
    }
  };

  const handlePublish = async () => {
    setReleaseAction('publish');
    try {
      const updated = await releaseRequest('publish');
      if (updated) setCourse(updated);
      toast.success(
        course?.source_instruction_id ? t('authenticatedUi.editor.publishedAssigned') : t('authenticatedUi.editor.published'),
        course?.source_instruction_id
          ? { description: t('authenticatedUi.editor.assignmentActivated') }
          : undefined,
      );
    } catch (error) {
      toast.error(t('authenticatedUi.editor.publishFailed'), { description: (error as Error).message });
    } finally {
      setReleaseAction(null);
    }
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!course) return <div className="p-6">{t('common.error')}</div>;

  return (
    <div className="mx-auto max-w-[1800px] space-y-6 px-4 py-5 sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <a
            href={`/courses/${courseId}`}
            onClick={(event) => void handleGuardedLink(event, `/courses/${courseId}`)}
            className="flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ChevronLeft className="w-4 h-4" /> {course.title}
          </a>
          <h1 className="text-2xl font-bold mt-1">{t('courses.editCourse')}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant={course.status === 'published' ? 'default' : 'outline'}>
              {course.status === 'published' ? t('courses.published') : t('courses.draft')}
            </Badge>
            {course.ai_generated && (
              <Badge variant={course.review_status === 'approved' ? 'secondary' : 'outline'}>
                {course.review_status === 'approved' ? t('authenticatedUi.editor.reviewed') : t('authenticatedUi.editor.needsReview')}
              </Badge>
            )}
            {course.source_instruction_id && <Badge variant="outline">{t('authenticatedUi.editor.byJobInstruction')}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          {course.status !== 'published' && course.ai_generated && course.review_status !== 'approved' && (
            <Button size="sm" variant="outline" onClick={handleApprove} disabled={releaseAction !== null || lessonDirty}>
              <CheckCircle2 className="mr-1.5 h-4 w-4" />
              {releaseAction === 'approve' ? t('authenticatedUi.editor.approving') : t('authenticatedUi.editor.approveCourse')}
            </Button>
          )}
          {course.status !== 'published' && (!course.ai_generated || course.review_status === 'approved') && (
            <Button size="sm" onClick={handlePublish} disabled={releaseAction !== null || lessonDirty}>
              <Rocket className="mr-1.5 h-4 w-4" />
              {releaseAction === 'publish'
                ? t('authenticatedUi.editor.publishing')
                : course.source_instruction_id
                  ? t('authenticatedUi.editor.publishAndAssign')
                  : t('authenticatedUi.editor.publish')}
            </Button>
          )}
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
            className="inline-flex min-h-9 items-center justify-center rounded-md border border-input px-3 py-2 text-sm font-medium hover:bg-muted"
          >
            {t('authenticatedUi.editor.approval')}
          </Link>
        </div>
      </div>
      <ApprovalPolicyCard courseId={course.id} initialRequiresApproval={Boolean(course.requires_approval)} />
      {course.status !== 'published' && course.ai_generated && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          {t('authenticatedUi.editor.quizReviewHint')}
        </div>
      )}

      {course.status !== 'published' && course.source_instruction_id && (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">
          {t('authenticatedUi.editor.draftVisibilityHint')}
        </div>
      )}

      <div className="grid min-h-[680px] gap-4 xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)_280px]">
        <Card className="min-h-0 xl:sticky xl:top-4 xl:h-[calc(100dvh-2rem)]">
          <CardContent className="flex h-full min-h-0 flex-col gap-4 p-4">
            <div className="flex items-center gap-2">
              <ListTree className="h-5 w-5 text-primary" aria-hidden="true" />
              <h2 className="font-semibold">{t('authenticatedUi.editor.outline')}</h2>
            </div>
            <div className="flex gap-2">
              <Input
                aria-label={t('courses.addModule')}
                placeholder={t('courses.addModule') + '...'}
                value={newModuleTitle}
                onChange={(event) => setNewModuleTitle(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && handleAddModule()}
              />
              <Button size="sm" onClick={handleAddModule} disabled={!newModuleTitle.trim()}>
                {t('common.create')}
              </Button>
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
              {modules.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">{t('courses.noCourses')}</p>
              ) : modules.map((mod, modIdx) => (
                <section key={mod.id} aria-labelledby={`module-${mod.id}`} className="space-y-2 rounded-lg border border-border/70 p-2">
                  {editingModuleId === mod.id ? (
                    <div className="space-y-2">
                      <Input value={editModuleTitle} onChange={(event) => setEditModuleTitle(event.target.value)} autoFocus onKeyDown={(event) => event.key === 'Enter' && handleUpdateModule(mod.id)} />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => handleUpdateModule(mod.id)}>{t('common.save')}</Button>
                        <Button variant="outline" size="sm" onClick={() => setEditingModuleId(null)}>{t('common.cancel')}</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-1">
                      <div className="flex flex-col gap-0.5">
                        <Button aria-label={t('authenticatedUi.editor.moveModuleUp')} variant="ghost" size="sm" className="h-5 px-1" onClick={() => handleMoveModule(mod.id, 'up')} disabled={modIdx === 0}><ChevronUp className="h-3 w-3" aria-hidden="true" /></Button>
                        <Button aria-label={t('authenticatedUi.editor.moveModuleDown')} variant="ghost" size="sm" className="h-5 px-1" onClick={() => handleMoveModule(mod.id, 'down')} disabled={modIdx === modules.length - 1}><ChevronDown className="h-3 w-3" aria-hidden="true" /></Button>
                      </div>
                      <h3 id={`module-${mod.id}`} className="min-w-0 flex-1 py-1 text-sm font-semibold leading-5">{mod.title}</h3>
                      <Button aria-label={t('common.edit')} variant="ghost" size="sm" className="h-8 px-2" onClick={() => { setEditingModuleId(mod.id); setEditModuleTitle(mod.title); }}><Pencil className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                      <Button aria-label={t('common.delete')} variant="ghost" size="sm" className="h-8 px-2 text-destructive" onClick={() => handleDeleteModule(mod.id)}><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                    </div>
                  )}
                  <div className="space-y-1">
                    {mod.lessons.map((lesson, lessonIdx) => (
                      <div key={lesson.id} className={`group flex items-center gap-1 rounded-md border ${editingLessonId === lesson.id ? 'border-primary bg-primary/10' : 'border-transparent hover:border-border hover:bg-muted/60'}`}>
                        <div className="flex flex-col">
                          <Button aria-label={t('authenticatedUi.editor.moveLessonUp')} variant="ghost" size="sm" className="h-4 px-1" onClick={() => handleMoveLesson(lesson.id, mod.id, 'up')} disabled={lessonIdx === 0}><ChevronUp className="h-3 w-3" aria-hidden="true" /></Button>
                          <Button aria-label={t('authenticatedUi.editor.moveLessonDown')} variant="ghost" size="sm" className="h-4 px-1" onClick={() => handleMoveLesson(lesson.id, mod.id, 'down')} disabled={lessonIdx === mod.lessons.length - 1}><ChevronDown className="h-3 w-3" aria-hidden="true" /></Button>
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
                      <Input placeholder={t('courses.addLesson') + '...'} value={newLessonTitle} onChange={(event) => setNewLessonTitle(event.target.value)} autoFocus onKeyDown={(event) => event.key === 'Enter' && handleAddLesson(mod.id)} />
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => handleAddLesson(mod.id)}>{t('common.create')}</Button>
                        <Button variant="outline" size="sm" onClick={() => { setAddingLessonToModule(null); setNewLessonTitle(''); }}>{t('common.cancel')}</Button>
                      </div>
                    </div>
                  ) : (
                    <Button variant="ghost" size="sm" className="w-full justify-start text-primary" onClick={() => setAddingLessonToModule(mod.id)}>+ {t('courses.addLesson')}</Button>
                  )}
                </section>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardContent className="flex min-h-[680px] flex-col p-0">
            {editingLessonId && activeLesson ? (
              <>
                <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t('authenticatedUi.editor.workspaceTitle')}</p>
                    <p className="truncate text-sm text-muted-foreground">{activeLesson.title}</p>
                  </div>
                  <div className="flex rounded-md border border-border p-1" role="group" aria-label={t('authenticatedUi.editor.viewMode')}>
                    <Button type="button" size="sm" variant={lessonView === 'edit' ? 'secondary' : 'ghost'} onClick={() => setLessonView('edit')}><Pencil className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('authenticatedUi.editor.editMode')}</Button>
                    <Button type="button" size="sm" variant={lessonView === 'preview' ? 'secondary' : 'ghost'} onClick={() => setLessonView('preview')}><Eye className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('authenticatedUi.editor.previewMode')}</Button>
                  </div>
                </div>
                {lessonView === 'edit' ? (
                  <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 sm:p-6">
                    <label className="block space-y-2">
                      <span className="text-sm font-medium">{t('authenticatedUi.editor.lessonTitle')}</span>
                      <Input value={editLessonTitle} onChange={(event) => setEditLessonTitle(event.target.value)} name="lesson-title" autoComplete="off" placeholder={t('authenticatedUi.editor.lessonTitlePlaceholder')} />
                    </label>
                    <label className="flex min-h-0 flex-1 flex-col gap-2">
                      <span className="text-sm font-medium">{t('authenticatedUi.editor.lessonContent')}</span>
                      <textarea
                        value={editLessonContent}
                        onChange={(event) => setEditLessonContent(event.target.value)}
                        name="lesson-content"
                        autoComplete="off"
                        className="min-h-[500px] w-full flex-1 resize-y rounded-md border border-input bg-background px-4 py-3 text-base leading-7 outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20"
                        placeholder={t('authenticatedUi.editor.lessonContentPlaceholder')}
                      />
                    </label>
                  </div>
                ) : (
                  <article className="min-h-[560px] overflow-x-auto p-6 sm:p-10">
                    <h1 className="mb-8 text-3xl font-bold tracking-tight">{editLessonTitle || t('authenticatedUi.editor.lessonTitle')}</h1>
                    <LessonContent
                      text={editLessonContent}
                      className="space-y-5 text-base leading-7 text-foreground [&_blockquote]:border-l-4 [&_blockquote]:border-primary/40 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_h1]:text-3xl [&_h1]:font-bold [&_h2]:mt-8 [&_h2]:text-2xl [&_h2]:font-semibold [&_h3]:mt-6 [&_h3]:text-xl [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:p-2 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-2 [&_th]:text-left [&_ul]:list-disc"
                    />
                  </article>
                )}
                <div className="flex flex-col gap-3 border-t border-border p-4 sm:flex-row sm:items-center sm:justify-between">
                  <p role="status" className={`text-sm ${lessonDirty ? 'text-amber-700' : 'text-muted-foreground'}`}>
                    {lessonDirty ? t('authenticatedUi.editor.unsavedChanges') : t('common.saved')}
                  </p>
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => void handleDiscardLessonChanges()} disabled={!lessonDirty || savingLesson}>{t('authenticatedUi.editor.discard')}</Button>
                    <Button onClick={handleSaveLessonContent} disabled={!lessonDirty || savingLesson || !editLessonTitle.trim()}>
                      {savingLesson && <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />}
                      {savingLesson ? t('common.saving') : t('common.save')}
                    </Button>
                  </div>
                </div>
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

        <aside className="space-y-4">
          <Card>
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
      {dialog}

      <AIChatPanel
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        courseId={courseId}
        focusLessonId={chatFocus.lessonId}
        focusLessonTitle={chatFocus.lessonTitle}
        focusModuleId={chatFocus.moduleId}
        focusModuleTitle={chatFocus.moduleTitle}
        onLessonApplied={() => fetchData()}
      />
    </div>
  );
}
