'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuthStore } from '@/store/authStore';
import { Card, CardHeader, CardTitle, CardContent, Button, Input, Badge } from '@/components/ui';
import { useT } from '@/i18n/useT';

export default function CoursesPage() {
  const { user, initialize, accessToken } = useAuthStore();
  const { t } = useT();
  const [courses, setCourses] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    fetchCourses();
  }, [search, statusFilter]);

  const fetchCourses = async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set('q', search);
      if (statusFilter) params.set('status', statusFilter);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses?${params}`, {
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      });
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
      headers: {
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({ title, description: description || '' }),
    });
    if (res.ok) {
      setShowCreate(false);
      setTitle('');
      setDescription('');
      fetchCourses();
    }
  };

  const handlePublish = async (courseId: string, currentStatus: string) => {
    const endpoint = currentStatus === 'published' ? 'unpublish' : 'publish';
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/courses/${courseId}/${endpoint}`, {
      method: 'POST',
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    if (res.ok) {
      fetchCourses();
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('courses.title')}</h1>
        <Button onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? t('common.cancel') : '+ ' + t('courses.createCourse')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <Input
          placeholder={t('common.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border rounded-md px-3 py-2 text-sm"
        >
          <option value="">{t('common.all')}</option>
          <option value="draft">{t('courses.draft')}</option>
          <option value="published">{t('courses.published')}</option>
          <option value="archived">В архиве</option>
        </select>
      </div>

      {showCreate && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>{t('courses.createCourse')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              placeholder={t('courses.courseTitle')}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <Input
              placeholder={t('courses.courseDescription')}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <Button onClick={handleCreate}>{t('common.create')}</Button>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <p className="text-gray-500">{t('common.loading')}</p>
      ) : courses.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {t('courses.noCourses')}
          </CardContent>
        </Card>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {courses.map((course) => (
            <Card key={course.id} className="hover:shadow-md transition-shadow">
              <CardHeader>
                <div className="flex items-start justify-between">
                  <CardTitle>{course.title}</CardTitle>
                  <Badge variant={course.status === 'published' ? 'default' : 'outline'}>
                    {course.status === 'published' ? t('courses.published') : course.status === 'draft' ? t('courses.draft') : course.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-gray-600 mb-4">{course.description}</p>
                <div className="flex gap-2">
                  <a href={`/courses/${course.id}/edit`}>
                    <Button variant="outline" className="flex-1">
                      {t('common.edit')}
                    </Button>
                  </a>
                  <Button
                    variant={course.status === 'published' ? 'secondary' : 'default'}
                    className="flex-1"
                    onClick={() => handlePublish(course.id, course.status)}
                  >
                    {course.status === 'published' ? t('courses.unpublish') : t('courses.publish')}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
