'use client';

import { useState, useEffect } from 'react';
import { useAuthStore } from '@/store/authStore';
import { Card, CardHeader, CardTitle, CardContent, Button, Input } from '@/components/ui';

export default function CoursesPage() {
  const { user, initialize } = useAuthStore();
  const [courses, setCourses] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    initialize();
    fetchCourses();
  }, [initialize]);

  const fetchCourses = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses`);
      if (res.ok) {
        const data = await res.json();
        setCourses(data);
      }
    } catch (e) {
      console.error('Failed to fetch courses', e);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!title.trim()) return;
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description: description || '' }),
    });
    if (res.ok) {
      setShowCreate(false);
      setTitle('');
      setDescription('');
      fetchCourses();
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-bold">Курсы</h1>
          <Button onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? 'Отмена' : '+ Создать курс'}
          </Button>
        </div>

        {showCreate && (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>Новый курс</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                placeholder="Название курса"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <Input
                placeholder="Описание"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <Button onClick={handleCreate}>Создать</Button>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <p className="text-gray-500">Загрузка...</p>
        ) : courses.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-gray-500">
              Нет курсов. Создайте первый!
            </CardContent>
          </Card>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {courses.map((course) => (
              <Card key={course.id}>
                <CardHeader>
                  <CardTitle>{course.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-gray-600 mb-4">{course.description}</p>
                  <div className="flex gap-2">
                    <a href={`/courses/${course.id}/edit`}>
                      <Button variant="outline" className="flex-1">
                        Редактировать
                      </Button>
                    </a>
                    <Button variant={course.status === 'published' ? 'secondary' : 'default'} className="flex-1">
                      {course.status === 'published' ? 'Опубликовано' : 'Опубликовать'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
