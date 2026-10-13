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
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const loadedRef = useRef(false);
  const generation = useRef(0);
  const canRequest = role === 'methodologist';
  const searchParams = useSearchParams();

  const load = useCallback(async () => {
    const current = ++generation.current;
    if (!loadedRef.current) setLoading(true);
    try {
      const [courseRows, requestRows] = await Promise.all([
        listApprovalCourses(canRequest ? 'authoring' : 'approval-audit'),
        listApprovalRequests(),
      ]);
      if (current !== generation.current) return;
      setError('');
      setCourses(courseRows);
      setRequests(requestRows);
      setCourseId((selected) => selected || searchParams.get('courseId') || courseRows[0]?.id || '');
    } catch {
      if (current !== generation.current) return;
      setError('Не удалось загрузить курсы и запросы согласования.');
    } finally {
      if (current === generation.current) { loadedRef.current = true; setLoading(false); }
    }
  }, [searchParams, canRequest]);
  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [load]);
  const selectedCourse = courses.find((course) => course.id === courseId);

  if (loading) return <div className="p-6">Загрузка…</div>;
  return <div className="mx-auto max-w-5xl space-y-6">
    <header><h1 className="text-2xl font-bold">Согласование курсов</h1><p className="mt-1 text-sm text-muted-foreground">{canRequest ? 'Настройте обязательную проверку, создайте снимок и отслеживайте решения рецензентов.' : 'Настройте обязательную проверку и просматривайте статусы запросов методиста.'}</p></header>
    {error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}
    <Card><CardContent className="space-y-3 p-5"><label className="block space-y-2 text-sm font-medium">Курс<select className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={courseId} onChange={(event) => { setOpen(false); setCourseId(event.target.value); }}><option value="">Выберите курс</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>{canRequest && !selectedCourse && <Input aria-label="Идентификатор курса" placeholder="Идентификатор курса (UUID)" value={courseId} onChange={(event) => setCourseId(event.target.value)} />}</CardContent></Card>
    {selectedCourse && <ApprovalPolicyCard key={`policy:${selectedCourse.id}`} courseId={selectedCourse.id} initialRequiresApproval={Boolean(selectedCourse.requires_approval)} />}
    {canRequest && selectedCourse && !error && <div className="flex flex-wrap gap-2"><Button type="button" onClick={() => setOpen(true)}>{t('courseApproval.createRequest')}</Button></div>}
    <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Статусы запросов</h2><Button type="button" size="sm" variant="outline" onClick={() => void load()}>Обновить</Button></div>{error ? <p role="status" className="text-sm text-muted-foreground">Статусы запросов не загружены. Повторите обновление.</p> : <ApprovalStatusPanel requests={requests} readOnly={!canRequest} onRefresh={() => void load()} />}</section>
    {canRequest && courseId && !error && <ApprovalRequestModal key={`request:${courseId}`} open={open} courseId={courseId} onClose={() => setOpen(false)} onCreated={() => void load()} />}
  </div>;
}
