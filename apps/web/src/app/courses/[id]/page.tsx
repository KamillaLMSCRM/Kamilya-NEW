'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { CheckCircle2, ChevronRight, ChevronLeft } from 'lucide-react';

interface Lesson {
  id: string;
  title: string;
  content_type: string;
  content: string | null;
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
}

export default function CoursePlayerPage() {
  const params = useParams();
  const courseId = params?.id as string;
  const { t } = useT();
  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);
  const [loading, setLoading] = useState(true);
  const [completedLessons, setCompletedLessons] = useState<Set<string>>(new Set());
  const [enrolled, setEnrolled] = useState<boolean | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [quizId, setQuizId] = useState<string | null>(null);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (courseId) {
      fetchData();
    }
  }, [courseId]);

  const fetchData = async () => {
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const [courseRes, structRes, progressRes, enrollRes] = await Promise.all([
        fetch(`${API_URL}/v1/courses/${courseId}`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/structure`, { headers }),
        fetch(`${API_URL}/v1/progress/courses/${courseId}/completed-ids`, { headers }),
        fetch(`${API_URL}/v1/courses/${courseId}/enrollments`, { headers }),
      ]);

      if (courseRes.ok) setCourse(await courseRes.json());

      // Check if user is enrolled
      if (enrollRes.ok) {
        const enrollData = await enrollRes.json();
        setEnrolled(enrollData.length > 0);
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
        const progressData = await progressRes.json();
        completedIds = new Set(progressData.completed_lesson_ids || []);
        setCompletedLessons(completedIds);
      }

      // Resume from last incomplete lesson, or start from first
      if (allLessons.length > 0) {
        const firstIncomplete = allLessons.find((l) => !completedIds.has(l.id));
        setSelectedLesson(firstIncomplete || allLessons[0]);
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
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
      });
      if (res.ok) {
        setEnrolled(true);
      } else {
        const err = await res.json();
        alert(err.detail || 'Не удалось записаться');
      }
    } finally {
      setEnrolling(false);
    }
  };

  const handleSelectLesson = async (lesson: Lesson) => {
    setSelectedLesson(lesson);
    setQuizId(null);
    if (lesson.content_type === 'quiz' && token) {
      try {
        const res = await fetch(`${API_URL}/v1/quizzes/by-lesson/${lesson.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setQuizId(data.id);
        }
      } catch { /* no quiz */ }
    }
  };

  const handleMarkComplete = async (lessonId: string) => {
    // Persist to backend
    if (token) {
      try {
        await fetch(`${API_URL}/v1/progress/lessons/${lessonId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ completed: true }),
        });
      } catch (e) {
        console.error('Failed to persist progress', e);
      }
    }

    setCompletedLessons((prev) => new Set(prev).add(lessonId));

    const nextLesson = findNextLesson(lessonId);
    if (nextLesson) {
      setSelectedLesson(nextLesson);
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

  const totalLessons = modules.reduce((acc, m) => acc + m.lessons.length, 0);
  const completedCount = completedLessons.size;
  const progressPercent = totalLessons > 0 ? Math.round((completedCount / totalLessons) * 100) : 0;

  if (loading) return <div className="p-6">Загрузка...</div>;
  if (!course) return <div className="p-6">Курс не найден</div>;

  // If not enrolled, show enroll prompt
  if (enrolled === false) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-lg shadow-md p-8 max-w-md w-full text-center">
          <h2 className="text-xl font-bold mb-2">{course.title}</h2>
          <p className="text-gray-600 mb-6">Запишитесь на курс, чтобы начать обучение</p>
          <button
            onClick={handleEnroll}
            disabled={enrolling}
            className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {enrolling ? 'Запись...' : 'Записаться на курс'}
          </button>
          <a href="/dashboard" className="block mt-4 flex items-center gap-1 text-sm text-blue-600 hover:underline">
            <ChevronLeft className="w-4 h-4" /> Вернуться
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Left sidebar — TOC */}
      <div className="w-80 bg-white border-r flex flex-col">
        <div className="p-4 border-b">
          <a href="/dashboard" className="flex items-center gap-1 text-sm text-blue-600 hover:underline">
            <ChevronLeft className="w-4 h-4" /> Мой дашборд
          </a>
          <h2 className="font-bold mt-2">{course.title}</h2>
          <div className="mt-2 h-2 bg-gray-200 rounded">
            <div className="h-2 bg-blue-600 rounded" style={{ width: `${progressPercent}%` }} />
          </div>
          <p className="text-xs text-gray-500 mt-1">{completedCount}/{totalLessons} уроков ({progressPercent}%)</p>
          <a href={`/courses/${courseId}/edit`} className="flex items-center gap-1 text-xs text-blue-500 hover:underline mt-1 inline-block">
            {t('courses.editCourse')} <ChevronRight className="w-3 h-3" />
          </a>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {modules.map((mod) => (
            <div key={mod.id}>
              <p className="text-xs font-semibold text-gray-400 uppercase mb-1">{mod.title}</p>
              {mod.lessons.map((lesson) => (
                <div
                  key={lesson.id}
                  className={`text-sm p-2 rounded cursor-pointer flex items-center gap-2 ${selectedLesson?.id === lesson.id ? 'bg-blue-50 text-blue-700 font-medium' : 'hover:bg-gray-50 text-gray-700'}`}
                  onClick={() => handleSelectLesson(lesson)}
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

      {/* Center — lesson content */}
      <div className="flex-1 p-8">
        {selectedLesson ? (
          <div className="max-w-3xl mx-auto">
            <h1 className="text-2xl font-bold mb-6">{selectedLesson.title}</h1>

            {selectedLesson.content_type === 'text' || selectedLesson.content_type === 'quiz' ? (
              <div className="prose max-w-none">
                {selectedLesson.content ? (
                  <div dangerouslySetInnerHTML={{ __html: simpleMarkdown(selectedLesson.content) }} />
                ) : (
                  <p className="text-gray-400 italic">Контент пока не добавлен</p>
                )}
              </div>
            ) : (
              <div className="bg-gray-200 rounded-lg h-64 flex items-center justify-center text-gray-400">
                Тип: {selectedLesson.content_type}
              </div>
            )}

            <div className="mt-8 flex gap-2">
              {selectedLesson.content_type === 'quiz' && quizId ? (
                <a href={`/courses/quiz/${quizId}`}>
                  <Button>Пройти тест <ChevronRight className="w-4 h-4 ml-1" /></Button>
                </a>
              ) : completedLessons.has(selectedLesson.id) ? (
                <span className="flex items-center gap-2 text-green-600 font-medium">
                  <CheckCircle2 className="w-5 h-5" /> Урок завершён
                </span>
              ) : (
                <Button onClick={() => handleMarkComplete(selectedLesson.id)}>
                  Завершить урок <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              )}
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
