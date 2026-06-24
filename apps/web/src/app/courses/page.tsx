'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useAuthStore } from '@/store/authStore';
import { Button, Input } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

export default function CoursesPage() {
  const { user } = useAuthStore();
  const { t } = useT();
  const { confirm, dialog } = useConfirm();
  const [courses, setCourses] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const canManage =
    user?.role === 'admin' ||
    user?.role === 'superadmin' ||
    user?.role === 'teacher' ||
    user?.role === 'org_admin';

  useEffect(() => {
    fetchCourses();
  }, [search, statusFilter]);

  const fetchCourses = async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.set('q', search);
      if (statusFilter) params.set('status', statusFilter);
      const res = await api.get(`/v1/courses?${params}`);
      setCourses(Array.isArray(res.data) ? res.data : []);
    } catch (err: any) {
      toast.error(t('common.loadFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!title.trim()) {
      toast.warning(t('common.required' as any));
      return;
    }
    try {
      await api.post('/v1/courses', { title, description: description || '' });
      setShowCreate(false);
      setTitle('');
      setDescription('');
      toast.success(t('toast.courseCreated'));
      fetchCourses();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    }
  };

  const handlePublish = async (courseId: string, currentStatus: string) => {
    const endpoint = currentStatus === 'published' ? 'unpublish' : 'publish';
    try {
      await api.post(`/v1/courses/${courseId}/${endpoint}`);
      fetchCourses();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    }
  };

  const handleDelete = async (courseId: string) => {
    const ok = await confirm({
      title: t('dialogs.confirmDeleteCourse'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    setDeletingId(courseId);
    try {
      await api.delete(`/v1/courses/${courseId}`);
      toast.success(t('toast.courseDeleted'));
      fetchCourses();
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-warm-800 font-display">{t('courses.title')}</h1>
        {canManage && (
          <Button onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? t('common.cancel') : '+ ' + t('courses.createCourse')}
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <label htmlFor="courses-search" className="sr-only">
            {t('common.search')}
          </label>
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 text-warm-400 pointer-events-none"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <Input
            id="courses-search"
            placeholder={t('common.search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <label htmlFor="courses-status" className="sr-only">
          {t('courses.status')}
        </label>
        <select
          id="courses-status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-xl border border-warm-200 bg-white px-3 py-2 text-sm text-warm-700 outline-none focus:border-primary transition-colors"
        >
          <option value="">{t('common.all')}</option>
          <option value="draft">{t('courses.draft')}</option>
          <option value="published">{t('courses.published')}</option>
        </select>
      </div>

      {showCreate && (
        <div className="rounded-2xl border border-warm-100 bg-white p-6 shadow-card space-y-4">
          <h3 className="font-bold text-warm-800 font-display">{t('courses.createCourse')}</h3>
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
          <div className="flex gap-2">
            <Button onClick={handleCreate}>{t('common.create')}</Button>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div
            className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent"
            aria-label={t('common.loading')}
          />
        </div>
      ) : courses.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-warm-200 py-12 text-center">
          <div className="text-warm-300 mb-3">
            <svg
              className="mx-auto"
              width="48"
              height="48"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
            </svg>
          </div>
          <p className="text-warm-400 text-sm">{t('courses.noCourses')}</p>
          {canManage && (
            <Link
              href="/ai/generate"
              className="inline-block mt-4 text-sm text-primary hover:underline"
            >
              {t('dashboard.aiGeneration')}
            </Link>
          )}
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {courses.map((course, i) => (
            <article
              key={course.id}
              className="group relative rounded-2xl border border-warm-100 bg-white overflow-hidden shadow-card hover:shadow-card-hover transition-all duration-300 hover:-translate-y-1 animate-fade-up"
              style={{ opacity: 0, animationFillMode: 'forwards', animationDelay: `${i * 0.05}s` }}
            >
              {/* Gradient header */}
              <div
                className={`h-28 p-4 flex items-end relative overflow-hidden ${
                  course.status === 'published'
                    ? 'bg-gradient-to-br from-primary/20 via-primary/10 to-gold-500/10'
                    : 'bg-gradient-to-br from-warm-100 via-warm-50 to-warm-100'
                }`}
              >
                {/* Decorative circles */}
                <div className="absolute -right-6 -top-6 h-20 w-20 rounded-full bg-primary/5" aria-hidden="true" />
                <div className="absolute -right-2 -bottom-4 h-16 w-16 rounded-full bg-gold-500/5" aria-hidden="true" />

                <div className="relative flex items-center gap-2">
                  <span
                    className={`text-[11px] font-semibold rounded-full px-2.5 py-1 backdrop-blur-sm ${
                      course.status === 'published'
                        ? 'text-primary bg-white/80'
                        : 'text-warm-500 bg-white/80'
                    }`}
                  >
                    {course.status === 'published' ? t('courses.published') : t('courses.draft')}
                  </span>
                  {course.ai_generated && (
                    <span className="text-[11px] font-semibold rounded-full px-2.5 py-1 text-gold-600 bg-gold-500/10 backdrop-blur-sm">
                      AI
                    </span>
                  )}
                </div>
              </div>

              <div className="p-4">
                {/* Title is a link (uses Link, not nested anchor) */}
                <Link
                  href={`/courses/${course.id}`}
                  className="block text-sm font-bold text-warm-800 group-hover:text-primary transition-colors truncate"
                >
                  <h3>{course.title}</h3>
                </Link>
                {course.description && (
                  <p className="mt-1.5 text-xs text-warm-400 line-clamp-2 leading-relaxed">{course.description}</p>
                )}

                {canManage && (
                  <div className="mt-4 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handlePublish(course.id, course.status)}
                      className={`flex-1 rounded-xl px-3 py-2 text-xs font-medium transition-colors ${
                        course.status === 'published'
                          ? 'bg-warm-50 text-warm-600 hover:bg-warm-100'
                          : 'bg-primary/10 text-primary hover:bg-primary/20'
                      }`}
                    >
                      {course.status === 'published' ? t('courses.unpublish') : t('courses.publish')}
                    </button>
                    <Link
                      href={`/courses/${course.id}/edit`}
                      className="rounded-xl border border-warm-200 px-3 py-2 text-xs font-medium text-warm-500 hover:border-warm-300 hover:text-warm-700 transition-colors"
                    >
                      {t('common.edit')}
                    </Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(course.id)}
                      disabled={deletingId === course.id}
                      className="rounded-xl px-3 py-2 text-xs font-medium text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-50"
                      aria-label={t('dialogs.delete')}
                    >
                      {deletingId === course.id ? '…' : '✕'}
                    </button>
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {dialog}
    </div>
  );
}
