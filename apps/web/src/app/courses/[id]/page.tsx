'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { useRouter } from 'next/navigation';
import { CheckCircle2, ChevronRight, ChevronLeft, Clock, AlertTriangle } from 'lucide-react';

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
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

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

  const fetchData = async () => {
    try {
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;

      const [courseRes, structRes, progressRes, enrollRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses/${courseId}`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/structure`, { headers }),
        fetch(`${API_URL}/v1/progress/courses/${courseId}/completed-ids`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, { headers }),
      ]);

      if (courseRes.ok) setCourse(await courseRes.json());

      const userRole = user?.role;
      const bypass = userRole === 'admin' || userRole === 'superadmin' || userRole === 'teacher' || userRole === 'org_admin';
      if (bypass) {
        setEnrolled(true);
      } else if (enrollRes.ok) {
        const d = await enrollRes.json();
        setEnrolled(d.length > 0);
        if (d.length > 0 && d[0].status === 'completed') {
          setCourseCompleted(true);
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
    // Auto-complete course if all lessons done
    const total = modules.reduce((acc, m) => acc + m.lessons.length, 0);
    if (newCompleted.size >= total && total > 0 && token && courseId) {
      try {
        await fetch(`${API_URL}/v1/courses/${courseId}/complete`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        toast.success(t('toast.courseCompleted'));
        router.push('/courses');
      } catch {}
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
      try {
        await fetch(`${API_URL}/v1/courses/${courseId}/complete`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {}
      toast.success(t('toast.courseCompleted'));
      router.push('/courses');
    } else {
      // Not all lessons done — go back to courses
      router.push('/courses');
    }
  };

  const totalLessons = modules.reduce((acc, m) => acc + m.lessons.length, 0);
  const completedCount = completedLessons.size;
  const progressPercent = totalLessons > 0 ? Math.round((completedCount / totalLessons) * 100) : 0;

  if (loading) return <div className="p-6">Загрузка...</div>;
  if (!course) return <div className="p-6">Курс не найден</div>;

  if (enrolled === false) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-lg shadow-md p-8 max-w-md w-full text-center">
          <h2 className="text-xl font-bold mb-2">{course.title}</h2>
          <p className="text-gray-600 mb-6">Запишитесь на курс, чтобы начать обучение</p>
          <button onClick={handleEnroll} disabled={enrolling} className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
            {enrolling ? 'Запись...' : 'Записаться на курс'}
          </button>
          <a href="/courses" className="block mt-4 flex items-center gap-1 text-sm text-blue-600 hover:underline justify-center">
            <ChevronLeft className="w-4 h-4" /> Вернуться к курсам
          </a>
        </div>
      </div>
    );
  }

  if (courseCompleted) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-lg shadow-md p-8 max-w-md w-full text-center">
          <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <h2 className="text-xl font-bold mb-2">{course.title}</h2>
          <p className="text-gray-600 mb-6">Вы успешно завершили этот курс!</p>
          <a href="/courses" className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 inline-block">
            Вернуться к курсам
          </a>
        </div>
      </div>
    );
  }

  const lessonCompleted = selectedLesson ? completedLessons.has(selectedLesson.id) : false;
  const hasQuiz = lessonQuiz !== null;

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Left sidebar — TOC */}
      <div className="w-80 bg-white border-r flex flex-col">
        <div className="p-4 border-b">
          <a href="/courses" className="flex items-center gap-1 text-sm text-blue-600 hover:underline">
            <ChevronLeft className="w-4 h-4" /> Курсы
          </a>
          <h2 className="font-bold mt-2">{course.title}</h2>
          <div className="mt-2 h-2 bg-gray-200 rounded">
            <div className="h-2 bg-blue-600 rounded transition-all" style={{ width: `${progressPercent}%` }} />
          </div>
          <p className="text-xs text-gray-500 mt-1">{completedCount}/{totalLessons} уроков ({progressPercent}%)</p>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {modules.map((mod) => (
            <div key={mod.id}>
              <p className="text-xs font-semibold text-gray-400 uppercase mb-1">{mod.title}</p>
              {mod.lessons.map((lesson) => (
                <div
                  key={lesson.id}
                  className={`text-sm p-2 rounded cursor-pointer flex items-center gap-2 ${selectedLesson?.id === lesson.id ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-gray-50 text-gray-700'}`}
                  onClick={() => setSelectedLesson(lesson)}
                >
                  <span className={`w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center text-xs ${completedLessons.has(lesson.id) ? 'bg-green-500 text-white border-green-500' : 'border-gray-300'}`}>
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
          <div className="max-w-3xl mx-auto">
            <h1 className="text-2xl font-bold mb-6">{selectedLesson.title}</h1>

            {/* Lesson content */}
            {selectedLesson.content_type === 'quiz' ? (
              <div className="prose max-w-none">
                {selectedLesson.content ? (
                  <div dangerouslySetInnerHTML={{ __html: simpleMarkdown(selectedLesson.content) }} />
                ) : (
                  <p className="text-gray-400 italic">Контент пока не добавлен</p>
                )}
              </div>
            ) : (
              <div className="prose max-w-none">
                {selectedLesson.content ? (
                  <div dangerouslySetInnerHTML={{ __html: simpleMarkdown(selectedLesson.content) }} />
                ) : (
                  <p className="text-gray-400 italic">Контент пока не добавлен</p>
                )}
              </div>
            )}

            {/* Action buttons */}
            <div className="mt-8 space-y-4">
              {/* Show quiz section if lesson is completed and quiz exists */}
              {lessonCompleted && hasQuiz && (
                <div className="border rounded-lg p-6 bg-white shadow-sm">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                      </svg>
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-800">{lessonQuiz.title}</h3>
                      <p className="text-sm text-gray-500">
                        Порог: {lessonQuiz.pass_score}%
                        {lessonQuiz.time_limit && ` · Время: ${lessonQuiz.time_limit} мин`}
                        {` · Попыток: ${lessonQuiz.attempt_limit}`}
                      </p>
                    </div>
                  </div>

                  {quizPassed ? (
                    <div className="flex items-center gap-2 text-green-600">
                      <CheckCircle2 className="w-5 h-5" />
                      <span className="font-medium">Тест пройден ({quizAttempts.find(a => a.passed)?.score_percent}%)</span>
                    </div>
                  ) : (
                    <>
                      {/* Deferral info */}
                      <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 rounded px-3 py-2 mb-4">
                        <Clock className="w-4 h-4" />
                        <span>Дедлайн: {lessonQuiz.deferral_days} дн. после завершения урока</span>
                      </div>

                      {/* Previous attempts */}
                      {quizAttempts.length > 0 && (
                        <div className="text-sm text-gray-500 mb-3">
                          Попыток: {quizAttempts.length}/{lessonQuiz.attempt_limit}
                          {quizAttempts.length > 0 && (
                            <span className="ml-2">· Лучший: {Math.max(...quizAttempts.map(a => a.score_percent))}%</span>
                          )}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <a href={`/courses/quiz/${lessonQuiz.id}`}>
                          <Button>Пройти тест <ChevronRight className="w-4 h-4 ml-1" /></Button>
                        </a>
                        <Button variant="outline" onClick={handleNextLesson}>
                          Отложить
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Mark complete / Next lesson */}
              {!lessonCompleted ? (
                <Button onClick={() => handleMarkComplete(selectedLesson.id)}>
                  Завершить урок <CheckCircle2 className="w-4 h-4 ml-1" />
                </Button>
              ) : !hasQuiz ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-2 text-green-600 font-medium">
                    <CheckCircle2 className="w-5 h-5" /> Урок завершён
                  </span>
                  <Button variant="outline" onClick={handleNextLesson}>
                    Далее <ChevronRight className="w-4 h-4 ml-1" />
                  </Button>
                </div>
              ) : quizPassed ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-2 text-green-600 font-medium">
                    <CheckCircle2 className="w-5 h-5" /> Урок + тест завершены
                  </span>
                  <Button variant="outline" onClick={handleNextLesson}>
                    Далее <ChevronRight className="w-4 h-4 ml-1" />
                  </Button>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400">
            Выберите урок из меню
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
