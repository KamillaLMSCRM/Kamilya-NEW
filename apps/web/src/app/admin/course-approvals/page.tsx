'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { ApprovalRequestModal } from '@/components/course-approval/ApprovalRequestModal';
import { ApprovalStatusPanel } from '@/components/course-approval/ApprovalStatusPanel';
import { listApprovalCourses, listApprovalRequests, type ApprovalCourseOption, type ApprovalRequestSummary } from '@/lib/courseApproval';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

export default function CourseApprovalsPage() {
  const user = useAuthStore((state) => state.user);
  if (user?.role !== 'methodologist' && user?.role !== 'admin') return <p role="alert">Нет доступа к согласованию курсов.</p>;
  // Discard selections, dialogs and in-flight reads when the active context changes.
  return <ApprovalWorkspace key={`${user.user_id}:${user.tenant_id}:${user.role}`} role={user.role} />;
}

function ApprovalWorkspace({ role }: { role: 'admin' | 'methodologist' }) {
  const { t } = useT();
  const [courses, setCourses] = useState<ApprovalCourseOption[]>([]);
  const [courseId, setCourseId] = useState('');
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [requestsCourseId, setRequestsCourseId] = useState('');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [requestLoading, setRequestLoading] = useState(false);
  const [error, setError] = useState('');
  const [requestError, setRequestError] = useState('');
  const loadedRef = useRef(false);
  const generation = useRef(0);
  const requestGeneration = useRef(0);
  const activeCourseIdRef = useRef('');
  const mountedRef = useRef(true);
  const canRequest = role === 'methodologist';
  const searchParams = useSearchParams();

  const loadCourses = useCallback(async () => {
    const current = ++generation.current;
    if (!loadedRef.current) setLoading(true);
    try {
      const courseRows = await listApprovalCourses(canRequest ? 'authoring' : 'approval-audit');
      if (current !== generation.current) return;
      setError('');
      setCourses(courseRows);
      setCourseId((selected) => {
        const next = selected || searchParams.get('courseId') || courseRows[0]?.id || '';
        activeCourseIdRef.current = next;
        return next;
      });
    } catch {
      if (current !== generation.current) return;
      setError('Не удалось загрузить курсы согласования.');
    } finally {
      if (current === generation.current) { loadedRef.current = true; setLoading(false); }
    }
  }, [searchParams, canRequest]);
  const loadRequests = useCallback(async (selectedCourseId = courseId) => {
    if (!mountedRef.current || activeCourseIdRef.current !== selectedCourseId) return;
    const current = ++requestGeneration.current;
    setRequestsCourseId('');
    if (!selectedCourseId) {
      setRequests([]);
      setRequestError('');
      setRequestLoading(false);
      return;
    }
    setRequests([]);
    setRequestError('');
    setRequestLoading(true);
    try {
      const requestRows = await listApprovalRequests(undefined, selectedCourseId);
      if (current !== requestGeneration.current || !mountedRef.current || activeCourseIdRef.current !== selectedCourseId) return;
      setRequests(requestRows);
      setRequestsCourseId(selectedCourseId);
    } catch {
      if (current !== requestGeneration.current || !mountedRef.current || activeCourseIdRef.current !== selectedCourseId) return;
      setRequestError('Не удалось загрузить запросы согласования.');
    } finally {
      if (current === requestGeneration.current && mountedRef.current && activeCourseIdRef.current === selectedCourseId) setRequestLoading(false);
    }
  }, [courseId]);
  useEffect(() => { mountedRef.current = true; void loadCourses(); return () => { generation.current += 1; mountedRef.current = false; }; }, [loadCourses]);
  useEffect(() => { void loadRequests(); return () => { requestGeneration.current += 1; }; }, [loadRequests]);
  const selectedCourse = courses.find((course) => course.id === courseId);
  const requestsReady = Boolean(courseId) && !requestLoading && !requestError && requestsCourseId === courseId;

  if (loading) return <div className="p-6">Загрузка…</div>;
  return <div className="mx-auto max-w-5xl space-y-6">
    <header><h1 className="text-2xl font-bold">Согласование курсов</h1><p className="mt-1 text-sm text-muted-foreground">{canRequest ? 'Настройте обязательную проверку, создайте снимок и отслеживайте решения рецензентов.' : 'Настройте обязательную проверку и просматривайте статусы запросов методиста.'}</p></header>
    {error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}
    <Card><CardContent className="space-y-3 p-5"><label className="block space-y-2 text-sm font-medium">Курс<select className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={courseId} onChange={(event) => { const next = event.target.value; activeCourseIdRef.current = next; setOpen(false); setRequests([]); setRequestError(''); setRequestLoading(Boolean(next)); setCourseId(next); }}><option value="">Выберите курс</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>{canRequest && !selectedCourse && <Input aria-label="Идентификатор курса" placeholder="Идентификатор курса (UUID)" value={courseId} onChange={(event) => { activeCourseIdRef.current = event.target.value; setRequests([]); setRequestError(''); setRequestLoading(Boolean(event.target.value)); setCourseId(event.target.value); }} />}</CardContent></Card>
    {selectedCourse && <ApprovalPolicyCard key={`policy:${selectedCourse.id}`} courseId={selectedCourse.id} initialRequiresApproval={Boolean(selectedCourse.requires_approval)} />}
    {canRequest && selectedCourse && !error && requestsReady && <div className="flex flex-wrap gap-2"><Button type="button" onClick={() => setOpen(true)}>{t('courseApproval.createRequest')}</Button></div>}
    <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Статусы запросов</h2><Button type="button" size="sm" variant="outline" onClick={() => { void loadCourses(); void loadRequests(); }}>Обновить</Button></div>{error || requestError ? <p role="status" className="text-sm text-muted-foreground">Статусы запросов не загружены. Повторите обновление.</p> : requestLoading || (courseId && !requestsReady) ? <p role="status" className="text-sm text-muted-foreground">Загрузка статусов запросов…</p> : !courseId ? <p role="status" className="text-sm text-muted-foreground">Выберите курс, чтобы просмотреть запросы согласования.</p> : <ApprovalStatusPanel requests={requests} readOnly={!canRequest} onRefresh={() => void loadRequests()} />}</section>
    {canRequest && courseId && !error && <ApprovalRequestModal key={`request:${courseId}`} open={open} courseId={courseId} onClose={() => setOpen(false)} onCreated={() => void loadRequests()} />}
  </div>;
}
