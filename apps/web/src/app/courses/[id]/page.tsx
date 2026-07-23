'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button } from '@/components/ui';
import Link from 'next/link';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { useRouter } from 'next/navigation';
import { CheckCircle2, ChevronRight, ChevronLeft, Clock, AlertTriangle } from 'lucide-react';
import { clearAuth } from '@/lib/auth';
import { useIdleTimeout } from '@/lib/useIdleTimeout';

interface Lesson {
  id: string;
  title: string;
  content_type: string;
  content: string | null;
  order_index: number;
  quiz_id?: string | null;
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
  delivery_type?: 'native' | 'scorm';
}

interface QuizInfo {
  id: string;
  title: string;
  pass_score: number;
  time_limit: number | null;
  attempt_limit: number;
  deferral_days: number;
}

interface QuizAttempt {
  score_percent: number;
  passed: boolean;
  completed_at: string;
}

interface AssistantMessage {
  id?: string;
  role: 'user' | 'assistant';
  content: string;
}

export default function CoursePlayerPage() {
  const params = useParams();
  const courseId = params?.id as string;
  const { t } = useT();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);
  const [loading, setLoading] = useState(true);
  const [completedLessons, setCompletedLessons] = useState<Set<string>>(new Set());
  const [enrolled, setEnrolled] = useState<boolean | null>(null);
  const [courseCompleted, setCourseCompleted] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [lessonQuiz, setLessonQuiz] = useState<QuizInfo | null>(null);
  const [quizAttempts, setQuizAttempts] = useState<QuizAttempt[]>([]);
  const [quizPassed, setQuizPassed] = useState(false);
  const [scormLaunchUrl, setScormLaunchUrl] = useState('');
  const [scormLaunchError, setScormLaunchError] = useState('');
  const [scormLaunchLoading, setScormLaunchLoading] = useState(false);
  const [assistantMessages, setAssistantMessages] = useState<AssistantMessage[]>([]);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [kioskSession, setKioskSession] = useState(false);
  const [kioskWarningSeconds, setKioskWarningSeconds] = useState<number | null>(null);
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setKioskSession(sessionStorage.getItem('kamilya_kiosk_session') === '1');
    }
  }, []);

  const exitKioskCourse = useCallback(() => {
    const returnPath = typeof window !== 'undefined'
      ? sessionStorage.getItem('kamilya_kiosk_return') || '/login'
      : '/login';
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem('kamilya_kiosk_session');
      sessionStorage.removeItem('kamilya_kiosk_return');
    }
    clearAuth();
    router.push(returnPath);
  }, [router]);

  const { warningSeconds } = useIdleTimeout({
    enabled: kioskSession,
    onTimeout: exitKioskCourse,
  });

  useEffect(() => {
    setKioskWarningSeconds(warningSeconds);
  }, [warningSeconds]);

  const fetchQuizForLesson = useCallback(async (lessonId: string) => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/quizzes/by-lesson/${lessonId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const quiz: QuizInfo = await res.json();
        setLessonQuiz(quiz);

        // Fetch attempts for this quiz
        const attemptsRes = await fetch(`${API_URL}/v1/quizzes/${quiz.id}/attempts`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (attemptsRes.ok) {
          const attempts: QuizAttempt[] = await attemptsRes.json();
          setQuizAttempts(attempts);
          setQuizPassed(attempts.some((a) => a.passed));
        }
      } else {
        setLessonQuiz(null);
        setQuizAttempts([]);
        setQuizPassed(false);
      }
    } catch {
      setLessonQuiz(null);
      setQuizAttempts([]);
      setQuizPassed(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    if (courseId) fetchData();
  }, [courseId]);

  useEffect(() => {
    if (selectedLesson) {
      fetchQuizForLesson(selectedLesson.id);
    }
  }, [selectedLesson, fetchQuizForLesson]);

  useEffect(() => {
    if (!token || !courseId || !selectedLesson || course?.delivery_type === 'scorm') return;
    let cancelled = false;
    const loadMessages = async () => {
      try {
        const res = await fetch(`${API_URL}/v1/learner/assistant/messages?course_id=${courseId}&lesson_id=${selectedLesson.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) {
          setAssistantMessages((Array.isArray(data) ? data : []).map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
          })));
        }
      } catch {}
    };
    loadMessages();
    return () => {
      cancelled = true;
    };
  }, [token, courseId, selectedLesson?.id, course?.delivery_type, API_URL]);

  useEffect(() => {
    if (course?.delivery_type !== 'scorm' || !token || !courseId) return;
    let cancelled = false;
    const loadLaunch = async () => {
      setScormLaunchLoading(true);
      setScormLaunchError('');
      try {
        const res = await fetch(`${API_URL}/v1/scorm/courses/${courseId}/launch`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          const detail = await res.json().catch(() => null);
          throw new Error(typeof detail?.detail === 'string' ? detail.detail : `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!cancelled) setScormLaunchUrl(data.launch_url);
      } catch (e) {
        if (!cancelled) setScormLaunchError(e instanceof Error ? e.message : 'Не удалось открыть SCORM');
      } finally {
        if (!cancelled) setScormLaunchLoading(false);
      }
    };
    loadLaunch();
    return () => {
      cancelled = true;
    };
  }, [course?.delivery_type, token, courseId, API_URL]);

  const fetchData = async () => {
    try {
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;

      const [courseRes, structRes, progressRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses/${courseId}`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/structure`, { headers }),
        fetch(`${API_URL}/v1/progress/courses/${courseId}/completed-ids`, { headers }),
      ]);

      if (courseRes.ok) setCourse(await courseRes.json());

      const userRole = user?.role;
      const bypass = userRole === 'admin' || userRole === 'superadmin' || userRole === 'methodologist' || userRole === 'org_admin';
      if (bypass) {
        setEnrolled(true);
      } else if (userRole === 'student') {
        const dashboardRes = await fetch(`${API_URL}/v1/student/dashboard`, { headers });
        if (dashboardRes.ok) {
          const dashboard = await dashboardRes.json();
          const enrolledCourse = (dashboard.enrolled_courses || []).find(
            (item: { course_id: string; enrollment_status?: string }) => item.course_id === courseId
          );
          setEnrolled(Boolean(enrolledCourse));
          setCourseCompleted(enrolledCourse?.enrollment_status === 'completed');
        } else {
          setEnrolled(false);
        }
      } else {
        setEnrolled(false);
      }

      let allLessons: Lesson[] = [];
      if (structRes.ok) {
        const data = await structRes.json();
        setModules(data.modules || []);
        allLessons = (data.modules || []).flatMap((m: Module) => m.lessons || []);
      }

      let completedIds: Set<string> = new Set();
      if (progressRes.ok) {
        const d = await progressRes.json();
        completedIds = new Set(d.completed_lesson_ids || []);
        setCompletedLessons(completedIds);
      }

      if (allLessons.length > 0) {
        const first = allLessons.find((l) => !completedIds.has(l.id));
        setSelectedLesson(first || allLessons[0]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleEnroll = async () => {
    if (!token || !courseId) return;
    setEnrolling(true);
    try {
      const res = await fetch(`${API_URL}/v1/courses/${courseId}/enroll`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setEnrolled(true);
        toast.success(t('toast.enrollSuccess'));
      } else {
        const err = await res.json();
        toast.error(t('toast.enrollError'), { description: err.detail });
      }
    } finally {
      setEnrolling(false);
    }
  };

  const handleMarkComplete = async (lessonId: string) => {
    if (token) {
      try {
        await fetch(`${API_URL}/v1/progress/lessons/${lessonId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ completed: true }),
        });
      } catch (e) {
        console.error('Failed to persist progress', e);
      }
    }
    const newCompleted = new Set(completedLessons).add(lessonId);
    setCompletedLessons(newCompleted);
    if (selectedLesson?.id === lessonId && lessonQuiz && !quizPassed) {
      return;
    }
    // Auto-complete course if all lessons and required quizzes are done.
    const total = modules.reduce((acc, m) => acc + m.lessons.length, 0);
    if (newCompleted.size >= total && total > 0 && token && courseId) {
      await finalizeCourseCompletion();
    }
  };

  const findNextLesson = (currentId: string): Lesson | null => {
    let found = false;
    for (const mod of modules) {
      for (const lesson of mod.lessons) {
        if (found) return lesson;
        if (lesson.id === currentId) found = true;
      }
    }
    return null;
  };

  const handleNextLesson = () => {
    if (!selectedLesson) return;
    const next = findNextLesson(selectedLesson.id);
    if (next) {
      setSelectedLesson(next);
    } else {
      // Last lesson — check if course is complete
      checkCourseCompletion();
    }
  };

  const checkCourseCompletion = async () => {
    const total = modules.reduce((acc, m) => acc + m.lessons.length, 0);
    if (completedLessons.size >= total && total > 0 && token && courseId) {
      await finalizeCourseCompletion();
    } else {
      // Not all lessons done — go back to courses
      router.push('/courses');
    }
  };

  // Finalizes course: calls /complete, auto-issue cert happens server-side.
  // Shows a toast with a "View certificate" action if a cert was issued.
  const finalizeCourseCompletion = async () => {
    if (!token || !courseId) {
      router.push('/courses');
      return;
    }
    try {
      const res = await fetch(`${API_URL}/v1/courses/${courseId}/complete`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        // The API normalizes structured FastAPI errors to
        // { error, message, details }. Keep accepting the legacy `detail`
        // shape as well so this flow remains compatible during rollouts.
        const details = payload?.details ?? payload?.detail;
        const reason = typeof details === 'object' && details !== null
          ? details.reason
          : undefined;
        if (reason === 'lessons_incomplete') {
          toast.error(t('common.saveFailed'), {
            description: `${details.completed_lessons}/${details.total_lessons}`,
          });
          return;
        }
        if (reason === 'quizzes_incomplete') {
          toast.error(t('common.saveFailed'), {
            description: `${details.passed_quizzes}/${details.total_quizzes}`,
          });
          return;
        }
        const message = typeof payload?.message === 'string'
          ? payload.message
          : typeof payload?.detail === 'string'
            ? payload.detail
            : `HTTP ${res.status}`;
        throw new Error(message);
      }
      const data: { certificate_id?: string; status?: string } = await res.json().catch(() => ({}));
      toast.success(t('toast.courseCompleted'));
      if (data.certificate_id) {
        toast.success(t('toast.certificateIssued'), {
          description: data.certificate_id,
          action: {
            label: t('toast.viewCertificate'),
            onClick: () => router.push('/certificates'),
          },
        });
      }
      router.push('/courses');
    } catch (e) {
      console.error('Course completion failed', e);
      toast.error(t('common.saveFailed'), {
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  const handleAssistantSend = async () => {
    const message = assistantInput.trim();
    if (!message || !token || !selectedLesson) return;
    setAssistantInput('');
    setAssistantMessages((prev) => [...prev, { role: 'user', content: message }]);
    setAssistantLoading(true);
    try {
      const res = await fetch(`${API_URL}/v1/learner/assistant/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ course_id: courseId, lesson_id: selectedLesson.id, message }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(typeof detail?.detail === 'string' ? detail.detail : `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAssistantMessages((prev) => [...prev, { role: 'assistant', content: data.reply || '' }]);
    } catch (e) {
      setAssistantMessages((prev) => [...prev, {
        role: 'assistant',
        content: e instanceof Error ? `Не удалось ответить: ${e.message}` : 'Не удалось ответить',
      }]);
    } finally {
      setAssistantLoading(false);
    }
  };

  const totalLessons = modules.reduce((acc, m) => acc + m.lessons.length, 0);
  const completedCount = completedLessons.size;
  const progressPercent = totalLessons > 0 ? Math.round((completedCount / totalLessons) * 100) : 0;

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!course) return <div className="p-6">{t('errors.notFound')}</div>;

  const kioskSessionNotice = kioskSession && kioskWarningSeconds !== null ? (
    <div className="fixed inset-x-0 top-0 z-50 mx-auto max-w-2xl px-4 pt-4" role="status">
      <div className="rounded-lg border border-warning/30 bg-warning px-4 py-3 text-sm text-warning-foreground shadow-lg">
        Сеанс на общем устройстве завершится через {kioskWarningSeconds} сек. Продолжите работу, чтобы сохранить доступ.
      </div>
    </div>
  ) : null;

  if (enrolled === false) {
    return (
      <div className="min-h-screen bg-muted flex items-center justify-center">
        {kioskSessionNotice}
        <div className="bg-card rounded-lg shadow-md p-8 max-w-md w-full text-center">
          <h2 className="text-xl font-bold mb-2">{course.title}</h2>
          <p className="text-muted-foreground mb-6">{t('courses.enrollRequired')}</p>
          <button onClick={handleEnroll} disabled={enrolling} className="bg-primary text-white px-6 py-2 rounded hover:bg-primary disabled:opacity-50">
            {enrolling ? t('common.saving' as any) : t('courses.enrollButton')}
          </button>
          <Link href="/courses" className="block mt-4 flex items-center gap-1 text-sm text-primary hover:underline justify-center">
            <ChevronLeft className="w-4 h-4" /> {t('courses.backToCourses')}
          </Link>
        </div>
      </div>
    );
  }

  if (courseCompleted) {
    return (
      <div className="min-h-screen bg-muted flex items-center justify-center">
        <div className="bg-card rounded-lg shadow-md p-8 max-w-md w-full text-center">
          <CheckCircle2 className="w-16 h-16 text-success mx-auto mb-4" aria-hidden="true" />
          <h2 className="text-xl font-bold mb-2">{course.title}</h2>
          <p className="text-muted-foreground mb-6">{t('courses.courseComplete')}</p>
          <Link href="/courses" className="bg-primary text-white px-6 py-2 rounded hover:bg-primary inline-block">
            {t('courses.backToCourses')}
          </Link>
        </div>
      </div>
    );
  }

  if (course.delivery_type === 'scorm') {
    return (
      <div className="min-h-screen bg-muted flex flex-col">
        <div className="flex h-14 items-center justify-between border-b bg-card px-4">
          <div className="min-w-0">
            <Link href="/courses" className="flex items-center gap-1 text-sm text-primary hover:underline">
              <ChevronLeft className="w-4 h-4" /> {t('courses.title')}
            </Link>
            <h1 className="truncate text-sm font-semibold">{course.title}</h1>
          </div>
          <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">SCORM 1.2</span>
        </div>
        {scormLaunchLoading ? (
          <div className="flex flex-1 items-center justify-center text-muted-foreground">{t('common.loading')}</div>
        ) : scormLaunchError ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="max-w-lg rounded-xl border border-destructive/30 bg-card p-6 text-sm shadow-sm">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
                <div>
                  <p className="font-semibold text-foreground">Не удалось открыть SCORM-курс</p>
                  <p className="mt-1 text-muted-foreground">{scormLaunchError}</p>
                </div>
              </div>
            </div>
          </div>
        ) : scormLaunchUrl ? (
          <iframe
            title={course.title}
            src={scormLaunchUrl}
            className="block flex-1 border-0 bg-white"
            allow="fullscreen"
          />
        ) : null}
      </div>
    );
  }

  const lessonCompleted = selectedLesson ? completedLessons.has(selectedLesson.id) : false;
  const hasQuiz = lessonQuiz !== null;

  return (
    <div className="min-h-screen bg-muted flex">
      {kioskSessionNotice}
      {/* Left sidebar — TOC */}
      <div className="w-80 bg-card border-r flex flex-col">
        <div className="p-4 border-b">
          <Link href="/courses" className="flex items-center gap-1 text-sm text-primary hover:underline">
            <ChevronLeft className="w-4 h-4" /> {t('courses.title')}
          </Link>
          <h2 className="font-bold mt-2">{course.title}</h2>
          <div className="mt-2 h-2 bg-muted rounded">
            <div className="h-2 bg-primary rounded transition-all" style={{ width: `${progressPercent}%` }} />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {t('courses.lessonsCount', { done: completedCount, total: totalLessons })} ({progressPercent}%)
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {modules.map((mod) => (
            <div key={mod.id}>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">{mod.title}</p>
              {mod.lessons.map((lesson) => (
                <div
                  key={lesson.id}
                  className={`text-sm p-2 rounded cursor-pointer flex items-center gap-2 ${selectedLesson?.id === lesson.id ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted text-foreground'}`}
                  onClick={() => setSelectedLesson(lesson)}
                >
                  <span className={`w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center text-xs ${completedLessons.has(lesson.id) ? 'bg-success text-white border-success' : 'border-border'}`}>
                    {completedLessons.has(lesson.id) && <CheckCircle2 className="w-3 h-3" />}
                  </span>
                  {lesson.title}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Center — lesson content + quiz */}
      <div className="flex-1 p-8">
        {selectedLesson ? (
          <div className="mx-auto grid max-w-6xl gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="min-w-0">
            <h1 className="text-2xl font-bold mb-6">{selectedLesson.title}</h1>

            <div className="prose max-w-none">
              {selectedLesson.content ? (
                <div dangerouslySetInnerHTML={{ __html: simpleMarkdown(selectedLesson.content) }} />
              ) : (
                <p className="text-muted-foreground italic">{t('common.noData')}</p>
              )}
            </div>

            <div className="mt-8 space-y-4">
              {lessonCompleted && hasQuiz && (
                <div className="border rounded-lg p-6 bg-card shadow-sm">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-full bg-primary/15 flex items-center justify-center">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-foreground">{lessonQuiz.title}</h3>
                      <p className="text-sm text-muted-foreground">
                        {t('quiz.passScore')}: {lessonQuiz.pass_score}%
                        {lessonQuiz.time_limit && ` · ${lessonQuiz.time_limit} ${t('common.minutes')}`}
                        {` · ${t('quiz.attempts')}: ${lessonQuiz.attempt_limit}`}
                      </p>
                    </div>
                  </div>

                  {quizPassed ? (
                    <div className="flex items-center gap-2 text-success">
                      <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
                      <span className="font-medium">
                        {t('quiz.passed')} ({quizAttempts.find(a => a.passed)?.score_percent}%)
                      </span>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 text-sm text-warning bg-warning/10 rounded px-3 py-2 mb-4">
                        <Clock className="w-4 h-4" aria-hidden="true" />
                        <span>
                          {t('quiz.deferralDays')}: {lessonQuiz.deferral_days}
                        </span>
                      </div>

                      {quizAttempts.length > 0 && (
                        <div className="text-sm text-muted-foreground mb-3">
                          {t('quiz.attempts')}: {quizAttempts.length}/{lessonQuiz.attempt_limit}
                          {quizAttempts.length > 0 && (
                            <span className="ml-2">
                              · {t('common.of')} {Math.max(...quizAttempts.map(a => a.score_percent))}%
                            </span>
                          )}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <Link href={`/courses/quiz/${lessonQuiz.id}`}>
                          <Button>{t('quiz.startQuiz')} <ChevronRight className="w-4 h-4 ml-1" /></Button>
                        </Link>
                        <Button variant="outline" onClick={handleNextLesson}>
                          {t('courses.nextLesson')}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}

              {!lessonCompleted ? (
                <Button onClick={() => handleMarkComplete(selectedLesson.id)}>
                  {t('courses.markComplete')} <CheckCircle2 className="w-4 h-4 ml-1" />
                </Button>
              ) : !hasQuiz ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-2 text-success font-medium">
                    <CheckCircle2 className="w-5 h-5" aria-hidden="true" /> {t('courses.markComplete')}
                  </span>
                  <Button variant="outline" onClick={handleNextLesson}>
                    {t('courses.nextLesson')} <ChevronRight className="w-4 h-4 ml-1" />
                  </Button>
                </div>
              ) : quizPassed ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-2 text-success font-medium">
                    <CheckCircle2 className="w-5 h-5" aria-hidden="true" /> {t('quiz.passed')}
                  </span>
                  <Button variant="outline" onClick={handleNextLesson}>
                    {t('courses.nextLesson')} <ChevronRight className="w-4 h-4 ml-1" />
                  </Button>
                </div>
              ) : null}
            </div>
            </div>
            <aside className="h-fit rounded-xl border border-border bg-card p-4 shadow-sm">
              <div className="mb-3">
                <h2 className="text-sm font-semibold text-foreground">AI-ассистент по уроку</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Задайте вопрос по материалу. Ассистент не выбирает ответы теста за вас.
                </p>
              </div>
              <div className="max-h-[420px] space-y-3 overflow-y-auto rounded-lg bg-muted/40 p-3">
                {assistantMessages.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Пока нет сообщений.</p>
                ) : (
                  assistantMessages.map((m, idx) => (
                    <div key={m.id || idx} className={m.role === 'user' ? 'text-right' : 'text-left'}>
                      <div className={`inline-block max-w-[95%] rounded-lg px-3 py-2 text-sm ${
                        m.role === 'user'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-card text-foreground border border-border'
                      }`}>
                        {m.content}
                      </div>
                    </div>
                  ))
                )}
                {assistantLoading && <p className="text-xs text-muted-foreground">Ассистент думает...</p>}
              </div>
              <div className="mt-3 space-y-2">
                <textarea
                  value={assistantInput}
                  onChange={(e) => setAssistantInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleAssistantSend();
                    }
                  }}
                  placeholder="Что непонятно в этом уроке?"
                  className="min-h-[84px] w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                />
                <Button onClick={handleAssistantSend} disabled={assistantLoading || !assistantInput.trim()} className="w-full">
                  Спросить
                </Button>
              </div>
            </aside>
          </div>
        ) : (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            {t('common.search')}
          </div>
        )}
      </div>
    </div>
  );
}

function simpleMarkdown(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
}
