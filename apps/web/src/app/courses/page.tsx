'use client';

import { Suspense, useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import ContextualNavigation from '@/components/layout/ContextualNavigation';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { Button, Input } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { coursePublicationError } from '@/lib/coursePublicationError';
import { Archive, ArrowRight, BookOpen, ChevronDown, GraduationCap, MoreVertical, Search, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { LoadError } from '@/components/ui/LoadError';
import { RecordList } from '@/features/workspace-design/RecordList';
import { getCourseCatalogCopy } from '@/features/course-catalog/copy';

type BlueprintLocale = 'ru' | 'kk';
type ComplianceMode = 'lms_only' | 'blended' | 'external_certified';

interface CourseBlueprintCatalogItem {
  id: string;
  title: string;
  description: string;
  audience: string;
  applicability?: string;
  estimated_ready_percent: number;
  compliance_mode?: ComplianceMode;
  tags?: string[];
}

interface CourseWithBlueprintSource {
  source_analysis?: { blueprint?: { id?: string } };
}

interface CatalogCourse extends CourseWithBlueprintSource {
  id: string;
  title: string;
  description?: string;
  status: string;
  ai_generated?: boolean;
  review_status?: string;
  delivery_type?: string;
  current_release_id?: string | null;
}

type CourseResult = {
  query: string;
  phase: 'loading' | 'ready' | 'error';
  courses: CatalogCourse[];
  error?: string;
};

const COURSE_STATUS_FILTERS = new Set(['draft', 'published']);

function readCourseStatusFilter(value: string | null): string {
  return value && COURSE_STATUS_FILTERS.has(value) ? value : '';
}

function readCoursePage(value: string | null): number {
  const page = Number(value);
  return Number.isSafeInteger(page) && page >= 1 && page <= 1_000_000 ? page : 1;
}

const getSourceBlueprintId = (course: CourseWithBlueprintSource) =>
  course.source_analysis?.blueprint?.id;

export default function CoursesPage() {
  const { user, sessionEpoch } = useAuthStore();
  if (!user) return null;

  // Remount presentation on actor/session changes: no previous actor's cards,
  // open forms, confirmations or asynchronous continuations survive the switch.
  const actorKey = JSON.stringify([user.user_id, user.tenant_id, user.role, sessionEpoch]);
  return (
    <Suspense fallback={null}>
      <CourseCatalog key={actorKey} canManage={user.role === 'methodologist'} />
    </Suspense>
  );
}

function CourseCatalog({ canManage }: { canManage: boolean }) {
  const { t, lang } = useT();
  const copy = getCourseCatalogCopy(lang);
  const router = useRouter();
  const searchParams = useSearchParams();
  const tRef = useRef(t);
  tRef.current = t;
  const { confirm, dialog } = useConfirm();
  const [courseResult, setCourseResult] = useState<CourseResult>({ query: '', phase: 'loading', courses: [] });
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '');
  const [statusFilter, setStatusFilter] = useState(() => readCourseStatusFilter(searchParams.get('status')));
  const [page, setPage] = useState(() => readCoursePage(searchParams.get('page')));
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [blueprints, setBlueprints] = useState<CourseBlueprintCatalogItem[]>([]);
  const [blueprintsLoading, setBlueprintsLoading] = useState(true);
  const [blueprintsError, setBlueprintsError] = useState<string | null>(null);
  const [loadedBlueprintLocale, setLoadedBlueprintLocale] = useState('');
  const mounted = useRef(false);
  const courseRequest = useRef(0);
  const blueprintRequest = useRef(0);

  const blueprintLocale: BlueprintLocale = lang === 'kk' ? 'kk' : 'ru';
  const query = JSON.stringify([search, statusFilter, page]);
  const currentQuery = useRef(query);
  currentQuery.current = query;
  const currentBlueprintLocale = useRef(blueprintLocale);
  currentBlueprintLocale.current = blueprintLocale;
  const loading = courseResult.query !== query || courseResult.phase === 'loading';
  const loadError = !loading && courseResult.phase === 'error' ? courseResult.error : null;
  const courses = !loading && courseResult.phase === 'ready' ? courseResult.courses : [];
  const hasFilters = Boolean(search || statusFilter);
  const browserQuery = searchParams.toString();

  useEffect(() => {
    const params = new URLSearchParams(browserQuery);
    const nextSearch = params.get('q') ?? '';
    const nextStatus = readCourseStatusFilter(params.get('status'));
    setPage(readCoursePage(params.get('page')));
    setSearch((current) => current === nextSearch ? current : nextSearch);
    setStatusFilter((current) => current === nextStatus ? current : nextStatus);
  }, [browserQuery]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      courseRequest.current += 1;
      blueprintRequest.current += 1;
    };
  }, []);

  const apiErrorMessage = (error: any, fallback: string) =>
    error?.response?.data?.message
    || error?.response?.data?.detail?.message
    || error?.response?.data?.detail
    || error?.message
    || fallback;

  const replaceFilterQuery = useCallback((nextSearch: string, nextStatus: string, history: 'push' | 'replace' = 'push', nextPage = 1) => {
    setPage(nextPage);
    const params = new URLSearchParams();
    if (nextSearch) params.set('q', nextSearch);
    if (nextStatus) params.set('status', nextStatus);
    if (nextPage > 1) params.set('page', String(nextPage));
    const nextQuery = params.toString();
    router[history](nextQuery ? `/courses?${nextQuery}` : '/courses', { scroll: false });
  }, [router]);

  const fetchCourses = useCallback(async () => {
    if (!mounted.current || currentQuery.current !== query) return;
    const request = ++courseRequest.current;
    const isCurrent = () => mounted.current && request === courseRequest.current && currentQuery.current === query;
    setCourseResult({ query, phase: 'loading', courses: [] });
    try {
      const params = new URLSearchParams();
      if (search) params.set('q', search);
      if (statusFilter) params.set('status', statusFilter);
      params.set('per_page', '100');
      if (page > 1) params.set('page', String(page));
      const res = await api.get(`/v1/courses?${params}`);
      if (!isCurrent()) return;
      setCourseResult({ query, phase: 'ready', courses: Array.isArray(res.data) ? res.data : [] });
    } catch (err: any) {
      if (!isCurrent()) return;
      setCourseResult({ query, phase: 'error', courses: [], error: apiErrorMessage(err, tRef.current('common.loadFailed')) });
      toast.error(tRef.current('common.loadFailed'), {
        description: apiErrorMessage(err, tRef.current('common.loadFailed')),
      });
    }
  }, [search, statusFilter, page, query]);

  const refreshCourses = useRef(fetchCourses);
  refreshCourses.current = fetchCourses;

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  const fetchBlueprints = useCallback(async () => {
    if (!mounted.current || currentBlueprintLocale.current !== blueprintLocale) return;
    const request = ++blueprintRequest.current;
    const isCurrent = () => mounted.current && request === blueprintRequest.current && currentBlueprintLocale.current === blueprintLocale;
    setBlueprintsLoading(true);
    setBlueprintsError(null);
    try {
      const response = await api.get<CourseBlueprintCatalogItem[]>(`/v1/course-blueprints?locale=${blueprintLocale}`);
      if (!isCurrent()) return;
      setBlueprints(Array.isArray(response.data) ? response.data : []);
      setLoadedBlueprintLocale(blueprintLocale);
    } catch (error: any) {
      if (!isCurrent()) return;
      setBlueprintsError(apiErrorMessage(error, tRef.current('courses.blueprint.catalogLoadFailed')));
      setLoadedBlueprintLocale(blueprintLocale);
    } finally {
      if (isCurrent()) setBlueprintsLoading(false);
    }
  }, [blueprintLocale]);

  useEffect(() => {
    if (canManage) void fetchBlueprints();
  }, [canManage, fetchBlueprints]);

  const complianceLabel = (mode?: ComplianceMode) => {
    if (mode === 'blended') return t('courses.blueprint.complianceModes.blended');
    if (mode === 'external_certified') return t('courses.blueprint.complianceModes.externalCertified');
    return t('courses.blueprint.complianceModes.lmsOnly');
  };

  const handleCreate = async () => {
    if (!title.trim()) {
      toast.warning(t('common.required' as any));
      return;
    }
    try {
      await api.post('/v1/courses', { title, description: description || '' });
      if (!mounted.current) return;
      setShowCreate(false);
      setTitle('');
      setDescription('');
      toast.success(t('toast.courseCreated'));
      void refreshCourses.current();
    } catch (err: any) {
      if (!mounted.current) return;
      toast.error(t('common.saveFailed'), {
        description: apiErrorMessage(err, t('common.saveFailed')),
      });
    }
  };

  const handlePublish = async (courseId: string, currentStatus: string) => {
    const endpoint = currentStatus === 'published' ? 'unpublish' : 'publish';
    try {
      await api.post(`/v1/courses/${courseId}/${endpoint}`);
      if (!mounted.current) return;
      void refreshCourses.current();
    } catch (err: any) {
      if (!mounted.current) return;
      toast.error(t('common.saveFailed'), {
        description: coursePublicationError(err?.response?.data, t) || apiErrorMessage(err, t('common.saveFailed')),
      });
    }
  };

  const handleDelete = async (courseId: string) => {
    const ok = await confirm({
      title: t('dialogs.confirmDeleteCourse'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok || !mounted.current) return;
    setDeletingId(courseId);
    try {
      await api.delete(`/v1/courses/${courseId}`);
      if (!mounted.current) return;
      toast.success(t('toast.courseDeleted'));
      void refreshCourses.current();
    } catch (err: any) {
      if (!mounted.current) return;
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      if (mounted.current) setDeletingId(null);
    }
  };

  const handleArchive = async (courseId: string) => {
    const ok = await confirm({
      title: t('dialogs.confirmArchiveCourse'),
      variant: 'danger',
      confirmLabel: t('courses.archive'),
    });
    if (!ok || !mounted.current) return;
    setDeletingId(courseId);
    try {
      await api.post(`/v1/courses/${courseId}/archive`);
      if (!mounted.current) return;
      toast.success(t('toast.courseArchived'), {
        description: t('courses.archiveHint'),
      });
      void refreshCourses.current();
    } catch (err: any) {
      if (!mounted.current) return;
      toast.error(t('common.saveFailed'), {
        description: apiErrorMessage(err, t('common.saveFailed')),
      });
    } finally {
      if (mounted.current) setDeletingId(null);
    }
  };

  const renderCourse = (course: CatalogCourse) => (
    <article key={course.id} data-course-card className="flex min-w-0 flex-col rounded-2xl border border-border bg-card p-5 shadow-sm transition-colors hover:border-primary/40">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <BookOpen className="h-4 w-4 text-primary" aria-hidden="true" />
          {course.delivery_type === 'scorm' ? 'SCORM' : copy.nativeCourse}
        </span>
        <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${course.status === 'published' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`}>
          {course.status === 'published' ? t('courses.published') : course.status === 'draft' ? t('courses.draft') : course.status}
        </span>
      </div>
      <h3 className="mt-4 text-lg font-semibold leading-6 text-foreground [overflow-wrap:anywhere]">
        <Link href={`/courses/${course.id}`} className="rounded-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{course.title}</Link>
      </h3>
      {course.description && <p className="mt-2 line-clamp-2 text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{course.description}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {course.ai_generated && <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">AI</span>}
        {getSourceBlueprintId(course) && <span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{t('courses.blueprint.badge')}</span>}
        {(course.ai_generated || getSourceBlueprintId(course)) && course.status !== 'published' && course.review_status !== 'approved' && <span className="rounded-md bg-warning/10 px-2 py-1 text-xs font-medium text-warning">{t('courses.reviewRequired')}</span>}
      </div>

      {canManage ? (
        <div className="mt-auto pt-5">
          {course.status !== 'published' && getSourceBlueprintId(course) && (
            <Link href={`/courses/templates/${getSourceBlueprintId(course)}?course_id=${course.id}`} className="mb-2 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-center text-sm font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
              {t('courses.blueprint.open')}
            </Link>
          )}
          {course.status === 'published' && (
            <Link href={`/assignments?course_id=${course.id}`} className="mb-2 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-center text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              <GraduationCap className="h-4 w-4 shrink-0" aria-hidden="true" />
              {t('authenticatedUi.course.assignEmployees')}
            </Link>
          )}
          <div className="flex flex-wrap items-stretch gap-2">
            <Link href={`/courses/${course.id}/edit`} className="flex min-h-11 min-w-0 [flex:1_1_7rem] items-center justify-center rounded-xl border border-border px-2 py-2 text-center text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t('common.edit')}
            </Link>
            <div className="grid min-w-0 [flex:1_1_10rem] grid-cols-[minmax(0,1fr)_44px] items-center gap-2">
              {course.ai_generated && course.status !== 'published' && course.review_status !== 'approved' ? (
                <Link href={`/courses/${course.id}/edit`} className="flex min-h-11 min-w-0 items-center justify-center rounded-xl bg-primary/10 px-2 py-2 text-center text-xs font-semibold text-primary transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t('courses.reviewCourse')}</Link>
              ) : (
                <button type="button" onClick={() => handlePublish(course.id, course.status)} className={`min-h-11 min-w-0 rounded-xl px-2 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${course.status === 'published' ? 'bg-muted text-foreground hover:bg-muted/80' : 'bg-primary/10 text-primary hover:bg-primary/20'}`}>
                  {course.status === 'published' ? t('courses.unpublish') : t('courses.publish')}
                </button>
              )}
              <details className="group/actions relative">
                <summary className="flex min-h-11 min-w-11 cursor-pointer list-none items-center justify-center rounded-xl border border-border text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden" aria-label={t('common.actionsFor', { title: course.title })} title={t('common.actionsFor', { title: course.title })}>
                  <MoreVertical className="h-4 w-4" aria-hidden="true" />
                </summary>
                <div className="absolute bottom-full right-0 z-20 mb-2 min-w-40 rounded-xl border border-border bg-card p-1 shadow-card-lg">
                  {course.current_release_id ? (
                    <button type="button" onClick={() => handleArchive(course.id)} disabled={deletingId === course.id} className="flex min-h-11 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-warning transition-colors hover:bg-warning/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                      <Archive className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {deletingId === course.id ? '…' : t('courses.archive')}
                    </button>
                  ) : (
                    <button type="button" onClick={() => handleDelete(course.id)} disabled={deletingId === course.id} className="flex min-h-11 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                      <Trash2 className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {deletingId === course.id ? '…' : t('dialogs.delete')}
                    </button>
                  )}
                </div>
              </details>
            </div>
          </div>
        </div>
      ) : (
        <Link href={`/courses/${course.id}`} className="mt-auto flex min-h-11 items-center gap-2 pt-5 text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{copy.openCourse}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
      )}
    </article>
  );

  return (
    <div data-catalog-layout="workspace-v1" className="min-w-0 space-y-6">
      <header className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold tracking-tight text-foreground font-display">{t('courses.title')}</h1>
        </div>
        {canManage && (
          <div className="flex flex-wrap items-center gap-2 xl:max-w-xl xl:justify-end">
            <ContextualNavigation section="courses" />
            <Link href="/ai/generate" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              <Sparkles className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              {copy.generationJobs}
            </Link>
            <Button variant="outline" className="min-h-11" aria-expanded={showCreate} aria-controls="course-create" onClick={() => setShowCreate(!showCreate)}>
              {showCreate ? t('common.cancel') : copy.manualCreate}
            </Button>
            <Link href="/ai/generate?new=1" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              <Sparkles className="h-4 w-4" aria-hidden="true" />{copy.createFromDocuments}
            </Link>
          </div>
        )}
      </header>

      {canManage && showCreate && (
        <div id="course-create" className="rounded-2xl border border-border bg-card p-5 shadow-sm space-y-4 sm:p-6">
          <h3 className="font-bold text-foreground font-display">{copy.manualCreate}</h3>
          <label htmlFor="new-course-title" className="block text-sm font-medium text-foreground">
            {t('courses.courseTitle')}
          </label>
          <Input
            id="new-course-title"
            required
            placeholder={t('courses.courseTitle')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <label htmlFor="new-course-description" className="block text-sm font-medium text-foreground">
            {t('courses.courseDescription')}
          </label>
          <Input
            id="new-course-description"
            placeholder={t('courses.courseDescription')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="flex gap-2">
            <Button onClick={handleCreate} disabled={!title.trim()}>{t('common.create')}</Button>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              {t('common.cancel')}
            </Button>
          </div>
        </div>
      )}

      <section className="min-w-0 space-y-4" aria-labelledby="own-courses-title">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="own-courses-title" className="text-lg font-semibold text-foreground">{copy.ownCourses}</h2>
          {!loading && !loadError && <p className="text-sm text-muted-foreground" role="status">{copy.loadedList}: <span className="font-semibold text-foreground">{courses.length}</span></p>}
        </div>
        <p className="text-xs leading-5 text-muted-foreground">{copy.pageSize}</p>

        <div role="search" aria-label={copy.filters} className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4 sm:flex-row sm:flex-wrap sm:items-end">
          <div className="min-w-0 flex-1 sm:min-w-48">
            <label htmlFor="courses-search" className="mb-1.5 block text-xs font-medium text-muted-foreground">{copy.searchLabel}</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input id="courses-search" type="search" placeholder={copy.searchPlaceholder} value={search} onChange={(e) => { const value = e.target.value; setSearch(value); replaceFilterQuery(value, statusFilter, 'replace'); }} className="min-h-11 pl-9" />
            </div>
          </div>
          <div className="min-w-0 sm:w-48">
            <label htmlFor="courses-status" className="mb-1.5 block text-xs font-medium text-muted-foreground">{t('courses.status')}</label>
            <select id="courses-status" value={statusFilter} onChange={(e) => { const value = e.target.value; setStatusFilter(value); replaceFilterQuery(search, value); }} className="min-h-11 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring">
              <option value="">{t('common.all')}</option>
              <option value="draft">{t('courses.draft')}</option>
              <option value="published">{t('courses.published')}</option>
            </select>
          </div>
          {hasFilters && <Button variant="ghost" className="min-h-11" onClick={() => { setSearch(''); setStatusFilter(''); replaceFilterQuery('', ''); }}>{copy.resetFilters}</Button>}
        </div>

        <div data-course-catalog-results aria-busy={loading}>
          {loading ? (
            <div role="status" className="flex min-h-48 items-center justify-center gap-3 rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground">
              <span className="h-5 w-5 rounded-full border-2 border-primary border-t-transparent motion-safe:animate-spin" aria-hidden="true" />
              {t('common.loading')}
            </div>
          ) : loadError ? (
            <LoadError title={t('common.loadFailed')} message={loadError} retryLabel={t('common.retry')} onRetry={() => void fetchCourses()} />
          ) : courses.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-card px-5 py-12 text-center">
              <BookOpen className="mx-auto mb-4 h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <h3 className="font-semibold text-foreground">{page > 1 ? copy.emptyPage : hasFilters ? copy.filteredEmpty : t('courses.noCourses')}</h3>
              <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">{hasFilters ? copy.filteredEmptyHint : canManage ? copy.emptyHint : null}</p>
            </div>
          ) : (
            canManage ? (
              <RecordList key={query} records={courses} getId={(course) => course.id} title={(course) => course.title} mobileBackLabel={copy.backToList}
                description={(course) => course.delivery_type === 'scorm' ? 'SCORM' : copy.nativeCourse}
                status={(course) => course.status === 'published' ? t('courses.published') : course.status === 'draft' ? t('courses.draft') : course.status}
                detailsLabel={copy.openCourse} renderDetails={renderCourse} />
            ) : (
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))]">{courses.map(renderCourse)}</div>
            )
          )}
        </div>
        {(page > 1 || courses.length > 0) && <nav aria-label={copy.pagination} className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="outline" disabled={loading || page === 1} onClick={() => replaceFilterQuery(search, statusFilter, 'push', page - 1)}>{copy.previousPage}</Button>
          <span role="status" className="text-sm text-muted-foreground">{copy.page} {page}</span>
          <Button variant="outline" disabled={loading || Boolean(loadError) || courses.length < 100} onClick={() => replaceFilterQuery(search, statusFilter, 'push', page + 1)}>{copy.nextPage}</Button>
        </nav>}
      </section>

      {canManage && (
        <details data-blueprint-catalog className="group/blueprints rounded-2xl border border-border bg-card">
          <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 rounded-2xl p-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <span className="min-w-0">
              <span className="block text-base font-semibold text-foreground">{t('courses.blueprint.catalogTitle')}</span>
            </span>
            <ChevronDown className="h-5 w-5 shrink-0 text-muted-foreground transition-transform group-open/blueprints:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
          </summary>
          <div className="space-y-4 border-t border-border p-5">
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{t('courses.blueprint.catalogDescription')}</p>
            {blueprintsLoading || loadedBlueprintLocale !== blueprintLocale ? (
              <div role="status" className="py-6 text-center text-sm text-muted-foreground">{t('common.loading')}</div>
            ) : blueprintsError ? (
              <LoadError title={t('courses.blueprint.catalogLoadFailed')} message={blueprintsError} retryLabel={t('common.retry')} onRetry={() => void fetchBlueprints()} />
            ) : blueprints.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">{t('courses.blueprint.catalogEmpty')}</p>
            ) : (
              <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))]">
                {blueprints.map((blueprint) => (
                  <article key={blueprint.id} className="flex min-w-0 flex-col rounded-xl border border-border bg-background p-4">
                    <h3 className="font-semibold leading-6 text-foreground [overflow-wrap:anywhere]">{blueprint.title}</h3>
                    <span className="mt-2 text-xs font-medium text-primary">{complianceLabel(blueprint.compliance_mode)}</span>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">{blueprint.description}</p>
                    <dl className="mt-3 space-y-2 text-sm leading-6">
                      <div><dt className="inline font-medium text-foreground">{t('courses.blueprint.audience')}: </dt><dd className="inline text-muted-foreground">{blueprint.audience}</dd></div>
                      {blueprint.applicability && <div><dt className="inline font-medium text-foreground">{t('courses.blueprint.applicability')}: </dt><dd className="inline text-muted-foreground">{blueprint.applicability}</dd></div>}
                    </dl>
                    {!!blueprint.tags?.length && <div className="mt-3 flex flex-wrap gap-2">{blueprint.tags.map((tag) => <span key={tag} className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">{tag}</span>)}</div>}
                    <p className="mb-4 mt-3 text-xs leading-5 text-muted-foreground">{t('courses.blueprint.catalogNotMandatory')}</p>
                    <Link href={blueprint.id === 'kz-finance-information-security' ? '/courses/templates/kz-finance-information-security' : `/courses/templates/${encodeURIComponent(blueprint.id)}`} className="mt-auto inline-flex min-h-11 items-center justify-center rounded-xl border border-border bg-card px-3 py-2 text-center text-sm font-medium text-primary transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t('courses.blueprint.open')}</Link>
                  </article>
                ))}
              </div>
            )}
          </div>
        </details>
      )}

      {dialog}
    </div>
  );
}
