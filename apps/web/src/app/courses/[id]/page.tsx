'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button } from 'ui-kit';

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
  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);
  const [loading, setLoading] = useState(true);
  const [completedLessons, setCompletedLessons] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (courseId) {
      fetchData();
    }
  }, [courseId]);

  const fetchData = async () => {
    try {
      const [courseRes, structRes] = await Promise.all([
        fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}`),
        fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}/structure`),
      ]);

      if (courseRes.ok) setCourse(await courseRes.json());

      if (structRes.ok) {
        const data = await structRes.json();
        setModules(data.modules || []);
        if (data.modules?.[0]?.lessons?.[0]) {
          setSelectedLesson(data.modules[0].lessons[0]);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleMarkComplete = async (lessonId: string) => {
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

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Left sidebar — TOC */}
      <div className="w-80 bg-white border-r flex flex-col">
        <div className="p-4 border-b">
          <a href="/dashboard" className="text-sm text-blue-600 hover:underline">← Мой дашборд</a>
          <h2 className="font-bold mt-2">{course.title}</h2>
          <div className="mt-2 h-2 bg-gray-200 rounded">
            <div className="h-2 bg-blue-600 rounded" style={{ width: `${progressPercent}%` }} />
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
                    {completedLessons.has(lesson.id) ? '✓' : ''}
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
              <Button onClick={() => handleMarkComplete(selectedLesson.id)}>
                Завершить урок →
              </Button>
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
