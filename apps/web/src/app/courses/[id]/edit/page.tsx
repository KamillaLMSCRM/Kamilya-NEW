'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardContent, Button, Input, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { ChevronLeft, ChevronUp, ChevronDown, X, Plus } from 'lucide-react';

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
}

export default function CourseEditPage() {
  const params = useParams();
  const courseId = params?.id as string;
  const { t } = useT();
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
    if (!confirm('Удалить модуль со всеми уроками?') || !token) return;
    await fetch(`${API_URL}/v1/modules/${moduleId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setModules((prev) => prev.filter((m) => m.id !== moduleId));
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
    if (!confirm('Удалить урок?') || !token) return;
    await fetch(`${API_URL}/v1/lessons/${lessonId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    setModules((prev) => prev.map((m) =>
      m.id === moduleId ? { ...m, lessons: m.lessons.filter((l) => l.id !== lessonId) } : m
    ));
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
    // Persist reorder
    if (token) {
      await fetch(`${API_URL}/v1/modules/${moduleId}/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(lessons.map((l) => l.id)),
      });
    }
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!course) return <div className="p-6">{t('common.error')}</div>;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <a href={`/courses/${courseId}`} className="flex items-center gap-1 text-sm text-blue-600 hover:underline">
            <ChevronLeft className="w-4 h-4" /> {course.title}
          </a>
          <h1 className="text-2xl font-bold mt-1">{t('courses.editCourse')}</h1>
        </div>
        <Badge variant={course.status === 'published' ? 'default' : 'outline'}>
          {course.status === 'published' ? t('courses.published') : t('courses.draft')}
        </Badge>
      </div>

      {/* Add Module */}
      <Card>
        <CardContent className="p-4 flex gap-2">
          <Input
            placeholder={t('courses.addModule') + '...'}
            value={newModuleTitle}
            onChange={(e) => setNewModuleTitle(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddModule()}
          />
          <Button onClick={handleAddModule} disabled={!newModuleTitle.trim()}>
            {t('common.create')}
          </Button>
        </CardContent>
      </Card>

      {/* Modules list */}
      {modules.length === 0 ? (
        <div className="text-center text-gray-400 py-8">{t('courses.noCourses')}</div>
      ) : (
        <div className="space-y-4">
          {modules.map((mod, modIdx) => (
            <Card key={mod.id}>
              <CardContent className="p-4 space-y-3">
                {/* Module header */}
                <div className="flex items-center gap-2">
                  <div className="flex flex-col gap-0.5">
                    <Button variant="ghost" size="sm" className="h-5 px-1" onClick={() => handleMoveModule(mod.id, 'up')} disabled={modIdx === 0}><ChevronUp className="w-3 h-3" /></Button>
                    <Button variant="ghost" size="sm" className="h-5 px-1" onClick={() => handleMoveModule(mod.id, 'down')} disabled={modIdx === modules.length - 1}><ChevronDown className="w-3 h-3" /></Button>
                  </div>
                  {editingModuleId === mod.id ? (
                    <div className="flex gap-2 flex-1">
                      <Input value={editModuleTitle} onChange={(e) => setEditModuleTitle(e.target.value)} autoFocus onKeyDown={(e) => e.key === 'Enter' && handleUpdateModule(mod.id)} />
                      <Button size="sm" onClick={() => handleUpdateModule(mod.id)}>{t('common.save')}</Button>
                      <Button variant="outline" size="sm" onClick={() => setEditingModuleId(null)}>{t('common.cancel')}</Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 flex-1">
                      <h3 className="font-semibold">{mod.title}</h3>
                      <Badge variant="outline">{mod.lessons.length} {t('courses.lessons')}</Badge>
                      <Button variant="ghost" size="sm" onClick={() => { setEditingModuleId(mod.id); setEditModuleTitle(mod.title); }}>
                        {t('common.edit')}
                      </Button>
                      <Button variant="ghost" size="sm" className="text-red-500" onClick={() => handleDeleteModule(mod.id)}>
                        {t('common.delete')}
                      </Button>
                    </div>
                  )}
                </div>

                {/* Lessons */}
                <div className="ml-8 space-y-1">
                  {mod.lessons.map((lesson, lessonIdx) => (
                    <div key={lesson.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded text-sm">
                      <div className="flex flex-col gap-0.5">
                        <Button variant="ghost" className="h-4 px-1 text-xs" onClick={() => handleMoveLesson(lesson.id, mod.id, 'up')} disabled={lessonIdx === 0}><ChevronUp className="w-3 h-3" /></Button>
                        <Button variant="ghost" className="h-4 px-1 text-xs" onClick={() => handleMoveLesson(lesson.id, mod.id, 'down')} disabled={lessonIdx === mod.lessons.length - 1}><ChevronDown className="w-3 h-3" /></Button>
                      </div>
                      <span className="flex-1">{lesson.title}</span>
                      <Badge variant="outline" className="text-xs">{lesson.content_type}</Badge>
                      <Button variant="ghost" size="sm" className="text-red-500 text-xs" onClick={() => handleDeleteLesson(lesson.id, mod.id)}>
                        <X className="w-3 h-3" />
                      </Button>
                    </div>
                  ))}

                  {/* Add lesson */}
                  {addingLessonToModule === mod.id ? (
                    <div className="flex gap-2 mt-2">
                      <Input
                        placeholder={t('courses.addLesson') + '...'}
                        value={newLessonTitle}
                        onChange={(e) => setNewLessonTitle(e.target.value)}
                        autoFocus
                        onKeyDown={(e) => e.key === 'Enter' && handleAddLesson(mod.id)}
                      />
                      <Button size="sm" onClick={() => handleAddLesson(mod.id)}>{t('common.create')}</Button>
                      <Button variant="outline" size="sm" onClick={() => { setAddingLessonToModule(null); setNewLessonTitle(''); }}>{t('common.cancel')}</Button>
                    </div>
                  ) : (
                    <Button variant="ghost" size="sm" className="text-blue-600" onClick={() => setAddingLessonToModule(mod.id)}>
                      + {t('courses.addLesson')}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
