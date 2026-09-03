'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { ApprovalPolicyCard } from '@/components/course-approval/ApprovalPolicyCard';
import { ApprovalRequestModal } from '@/components/course-approval/ApprovalRequestModal';
import { ApprovalStatusPanel } from '@/components/course-approval/ApprovalStatusPanel';
import { listApprovalRequests, type ApprovalRequestSummary } from '@/lib/courseApproval';

interface CourseOption { id: string; title: string; requires_approval?: boolean }

export default function CourseApprovalsPage() {
  const [courses, setCourses] = useState<CourseOption[]>([]);
  const [courseId, setCourseId] = useState('');
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const searchParams = useSearchParams();

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [courseResponse, requestRows] = await Promise.all([
        api.get<CourseOption[] | { items?: CourseOption[] }>('/v1/courses?per_page=500'),
        listApprovalRequests(),
      ]);
      const data = Array.isArray(courseResponse.data) ? courseResponse.data : courseResponse.data.items || [];
      setCourses(data);
      setRequests(requestRows);
      setCourseId((current) => current || searchParams.get('courseId') || data[0]?.id || '');
    } catch { setError('Не удалось загрузить курсы и запросы согласования.'); }
    finally { setLoading(false); }
  }, [searchParams]);
  useEffect(() => { void load(); }, [load]);
  const selectedCourse = courses.find((course) => course.id === courseId);

  if (loading) return <div className="p-6">Загрузка…</div>;
  return <div className="mx-auto max-w-5xl space-y-6"><header><h1 className="text-2xl font-bold">Согласование курсов</h1><p className="mt-1 text-sm text-muted-foreground">Настройте обязательную проверку, создайте снимок и отслеживайте решения рецензентов.</p></header>{error && <p role="alert" className="break-words rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error}</p>}<Card><CardContent className="space-y-3 p-5"><label className="block space-y-2 text-sm font-medium">Курс<select className="flex h-10 w-full rounded-md border bg-background px-3 py-2 text-sm" value={courseId} onChange={(event) => setCourseId(event.target.value)}><option value="">Выберите курс</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>{!selectedCourse && <Input aria-label="Идентификатор курса" placeholder="Идентификатор курса (UUID)" value={courseId} onChange={(event) => setCourseId(event.target.value)} />}</CardContent></Card>{selectedCourse && <><ApprovalPolicyCard courseId={selectedCourse.id} initialRequiresApproval={Boolean(selectedCourse.requires_approval)} /><div className="flex flex-wrap gap-2"><Button onClick={() => setOpen(true)}>Создать запрос на согласование</Button></div></>}<section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Статусы запросов</h2><Button size="sm" variant="outline" onClick={() => void load()}>Обновить</Button></div><ApprovalStatusPanel requests={requests} onRefresh={() => void load()} /></section>{courseId && <ApprovalRequestModal open={open} courseId={courseId} onClose={() => setOpen(false)} onCreated={() => void load()} />}</div>;
}
