'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Button, Input, Card, CardHeader, CardTitle, CardContent } from '@/components/ui';
import CourseEditor from '@/components/CourseEditor';

interface Module {
  id: string;
  title: string;
  description: string;
  order_index: number;
  lessons: Lesson[];
}

interface Lesson {
  id: string;
  title: string;
  content_type: string;
  content: string | null;
  order_index: number;
}

interface Course {
  id: string;
  title: string;
  description: string;
  status: string;
  ai_generated: boolean;
  created_at: string;
  updated_at: string;
}

export default function CourseEditPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params?.id as string;
  const [course, setCourse] = useState<Course | null>(null);
  const [modules, setModules] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLesson, setSelectedLesson] = useState<Lesson | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [editingContent, setEditingContent] = useState('');
  const [showNewModule, setShowNewModule] = useState(false);
  const [newModuleTitle, setNewModuleTitle] = useState('');
  const [showNewLesson, setShowNewLesson] = useState<string | null>(null);
  const [newLessonTitle, setNewLessonTitle] = useState('');

  useEffect(() => {
    if (courseId) {
      fetchCourse();
      fetchModules();
    }
  }, [courseId]);

  const fetchCourse = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}`);
      if (res.ok) setCourse(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchModules = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}/modules`);
      if (res.ok) {
        const mods = await res.json();
        const withLessons = await Promise.all(
          mods.map(async (m: Module) => {
            const lr = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/modules/${m.id}/lessons`);
            return { ...m, lessons: lr.ok ? await lr.json() : [] };
          })
        );
        setModules(withLessons);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateModule = async () => {
    if (!newModuleTitle.trim()) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}/modules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newModuleTitle }),
    });
    setShowNewModule(false);
    setNewModuleTitle('');
    fetchModules();
  };

  const handleCreateLesson = async (moduleId: string) => {
    if (!newLessonTitle.trim()) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/modules/${moduleId}/lessons`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newLessonTitle, content_type: 'text' }),
    });
    setShowNewLesson(null);
    setNewLessonTitle('');
    fetchModules();
  };

  const handleSaveLesson = async () => {
    if (!selectedLesson) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/lessons/${selectedLesson.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: editingTitle, content: editingContent }),
    });
    fetchModules();
  };

  const handlePublish = async (status: string) => {
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    fetchCourse();
  };

  const handleDeleteModule = async (moduleId: string) => {
    if (!confirm('Удалить модуль?')) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/modules/${moduleId}`, { method: 'DELETE' });
    fetchModules();
  };

  const handleDeleteLesson = async (lessonId: string) => {
    if (!confirm('Удалить урок?')) return;
    await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/lessons/${lessonId}`, { method: 'DELETE' });
    setSelectedLesson(null);
    fetchModules();
  };

  if (loading) return <div className="p-6">Загрузка...</div>;
  if (!course) return <div className="p-6">Курс не найден</div>;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white border-b px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-4">
          <a href="/courses" className="text-blue-600 hover:underline">← Курсы</a>
          <h1 className="text-xl font-bold">{course.title}</h1>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${course.status === 'published' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
            {course.status}
          </span>
        </div>
        <div className="flex gap-2">
          {course.status === 'draft' ? (
            <Button onClick={() => handlePublish('published')}>Опубликовать</Button>
          ) : (
            <Button variant="outline" onClick={() => handlePublish('draft')}>Снять с публикации</Button>
          )}
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-6 grid grid-cols-12 gap-6">
        {/* Left: structure */}
        <div className="col-span-4 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Структура курса</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {modules.map((mod) => (
                <div key={mod.id} className="border rounded-lg p-3">
                  <div className="flex justify-between items-center mb-2">
                    <span className="font-medium text-sm">{mod.title}</span>
                    <div className="flex gap-1">
                      <button
                        onClick={() => setShowNewLesson(mod.id)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        + урок
                      </button>
                      <button
                        onClick={() => handleDeleteModule(mod.id)}
                        className="text-xs text-red-500 hover:underline ml-2"
                      >
                        удалить
                      </button>
                    </div>
                  </div>
                  <div className="ml-2 space-y-1">
                    {mod.lessons.map((lesson) => (
                      <div
                        key={lesson.id}
                        className={`flex justify-between items-center text-sm p-1 rounded cursor-pointer ${selectedLesson?.id === lesson.id ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-50'}`}
                        onClick={() => {
                          setSelectedLesson(lesson);
                          setEditingTitle(lesson.title);
                          setEditingContent(lesson.content || '');
                        }}
                      >
                        <span>• {lesson.title}</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteLesson(lesson.id); }}
                          className="text-xs text-red-400 hover:text-red-600"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    {showNewLesson === mod.id && (
                      <div className="flex gap-1 mt-1">
                        <Input
                          placeholder="Название урока"
                          value={newLessonTitle}
                          onChange={(e) => setNewLessonTitle(e.target.value)}
                          className="h-8 text-xs"
                          onKeyDown={(e) => e.key === 'Enter' && handleCreateLesson(mod.id)}
                        />
                        <Button size="sm" onClick={() => handleCreateLesson(mod.id)}>OK</Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {showNewModule ? (
                <div className="flex gap-1">
                  <Input
                    placeholder="Название модуля"
                    value={newModuleTitle}
                    onChange={(e) => setNewModuleTitle(e.target.value)}
                    className="h-8 text-sm"
                    onKeyDown={(e) => e.key === 'Enter' && handleCreateModule()}
                  />
                  <Button size="sm" onClick={handleCreateModule}>OK</Button>
                </div>
              ) : (
                <Button variant="outline" className="w-full" onClick={() => setShowNewModule(true)}>
                  + Добавить модуль
                </Button>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Center: lesson editor */}
        <div className="col-span-8">
          {selectedLesson ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Редактор урока</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-sm font-medium mb-1 block">Заголовок</label>
                  <Input
                    value={editingTitle}
                    onChange={(e) => setEditingTitle(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Контент (Markdown)</label>
                  <textarea
                    value={editingContent}
                    onChange={(e) => setEditingContent(e.target.value)}
                    className="w-full h-64 border rounded-lg p-3 font-mono text-sm"
                    placeholder="Напишите содержание урока..."
                  />
                </div>
                <div className="flex gap-2">
                  <Button onClick={handleSaveLesson}>Сохранить</Button>
                  <Button variant="outline" onClick={() => setSelectedLesson(null)}>Отмена</Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-20 text-center text-gray-400">
                Выберите урок из структуры для редактирования
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
