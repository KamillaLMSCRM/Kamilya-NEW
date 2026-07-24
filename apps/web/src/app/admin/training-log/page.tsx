'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Button,
  Badge,
  Table,
  Input,
} from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { Skeleton } from '@/components/ui/Skeleton';
import { canAccessRoute } from '@/lib/rolePolicy';
import {
  buildTrainingLogFilterQuery,
  buildTrainingLogPageQuery,
  type TrainingLogFilters,
} from './query';
import { TRAINING_LOG_COLUMN_CLASS as columnClass } from './presentation';

/**
 * Training log — единый журнал обучения (P0.3 first-tenant hardening).
 *
 * Backend: GET /api/v1/admin/training-log?…&format=csv
 *
 * Что показывает:
 * - Сотрудник × курс: ФИО, табельный, должность, отдел, курс (native/SCORM),
 *   статус enrollment, прогресс, лучший балл теста, дата завершения,
 *   сертификат, время последнего визита в киоск.
 * - Фильтры: курс, отдел, должность, статус (assigned/in_progress/completed/overdue),
 *   тип (native/scorm), диапазон дат, поиск по ФИО/email/табельному.
 * - Export CSV (UTF-8 BOM) с теми же фильтрами.
 * - Пагинация (limit/offset).
 */

interface TrainingLogRow {
  user_id: string;
  full_name: string;
  email: string | null;
  personnel_number: string | null;
  department_id: string | null;
  department_name: string | null;
  position_id: string | null;
  position_name: string | null;
  course_id: string;
  course_title: string;
  delivery_type: 'native' | 'scorm';
  enrollment_status: string;
  enrollment_source: string;
  enrolled_at: string | null;
  completed_at: string | null;
  // Computed by backend (2026-07-09): honest status from real activity data.
  // `overdue` was removed because enrollments have no deadline column —
  // would have been a misleading filter. UI drops the option too.
  computed_status: 'assigned' | 'in_progress' | 'completed';
  progress_percent: number;
  best_score: number | null;
  quiz_attempts_count: number;
  certificate_id: string | null;
  certificate_number: string | null;
  certificate_issued_at: string | null;
  kiosk_last_seen_at: string | null;
}

interface TrainingLogPage {
  items: TrainingLogRow[];
  total: number;
  limit: number;
  offset: number;
}

interface TrainingLogSummary {
  total: number;
  assigned: number;
  in_progress: number;
  completed: number;
}

type Filters = TrainingLogFilters;

// Mirrors backend TrainingLogFilter.status Literal (no `overdue`).
const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Все статусы' },
  { value: 'assigned', label: 'Назначен' },
  { value: 'in_progress', label: 'В процессе' },
  { value: 'completed', label: 'Завершён' },
];

const DELIVERY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Все типы' },
  { value: 'native', label: 'Нативный' },
  { value: 'scorm', label: 'SCORM 1.2' },
];

export default function AdminTrainingLogPage() {
  const { t, lang } = useT();
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);

  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState<TrainingLogPage | null>(null);
  const [summary, setSummary] = useState<TrainingLogSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);

  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(searchInput), 350);
    return () => clearTimeout(id);
  }, [searchInput]);

  const queryString = useMemo(() => {
    return buildTrainingLogPageQuery(filters, debouncedSearch, limit, offset);
  }, [debouncedSearch, filters, limit, offset]);

  const summaryQueryString = useMemo(() => (
    buildTrainingLogFilterQuery(filters, debouncedSearch).toString()
  ), [debouncedSearch, filters]);

  const fetchPage = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<TrainingLogPage>(
        `/v1/admin/training-log?${queryString}`,
      );
      setPage(res.data);
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail ||
        e?.message ||
        t('trainingLog.errors.loadFailed');
      setError(String(msg));
      toast.error(String(msg));
    } finally {
      setLoading(false);
    }
  }, [accessToken, queryString, t]);

  useEffect(() => {
    fetchPage();
  }, [fetchPage]);

  useEffect(() => {
    if (!accessToken) return;
    const suffix = summaryQueryString ? `?${summaryQueryString}` : '';
    api.get<TrainingLogSummary>(`/v1/admin/training-log/summary${suffix}`)
      .then((res) => setSummary(res.data))
      .catch(() => setSummary(null));
  }, [accessToken, summaryQueryString]);

  // Reset pagination when filters change (typical table UX).
  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, filters]);

  const exportCsv = useCallback(async () => {
    if (!accessToken) return;
    try {
      const res = await api.get(`/v1/admin/training-log?${queryString}&format=csv&lang=${lang}`, {
        responseType: 'blob',
      });
      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      a.download = `training-log-${ts}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t('trainingLog.export.success'));
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail ||
        e?.message ||
        t('trainingLog.errors.exportFailed');
      toast.error(String(msg));
    }
  }, [accessToken, lang, queryString, t]);

  // Auth gate: training-log is admin/HR work, not student work.
  if (user && !canAccessRoute(user.role, '/admin/training-log')) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        {t('trainingLog.forbidden')}
      </div>
    );
  }

  const total = page?.total ?? 0;
  const items = page?.items ?? [];
  const hasActiveFilters = Object.values(filters).some(Boolean) || Boolean(searchInput.trim());
  const resetFilters = () => {
    setFilters({});
    setSearchInput('');
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">
            {t('trainingLog.title')}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t('trainingLog.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={resetFilters}
          >
            {t('trainingLog.filters.reset')}
          </Button>
          <Button type="button" onClick={exportCsv} disabled={loading || total === 0}>
            {t('trainingLog.export.csv')}
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SummaryCard label={t('trainingLog.title')} value={summary?.total ?? 0} />
        <SummaryCard label={t('trainingLog.filter.status.assigned')} value={summary?.assigned ?? 0} />
        <SummaryCard label={t('trainingLog.filter.status.inProgress')} value={summary?.in_progress ?? 0} />
        <SummaryCard label={t('trainingLog.filter.status.completed')} value={summary?.completed ?? 0} />
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>{t('trainingLog.filters.title')}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3">
          <div className="md:col-span-2 lg:col-span-1">
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              {t('trainingLog.filter.search.label')}
            </label>
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder={t('trainingLog.filter.search.placeholder')}
            />
          </div>

          <SelectField
            label={t('trainingLog.filter.status.label')}
            value={filters.status ?? ''}
            options={STATUS_OPTIONS}
            onChange={(v) => setFilters((f) => ({ ...f, status: (v || undefined) as Filters['status'] }))}
          />

          <SelectField
            label={t('trainingLog.filter.delivery.label')}
            value={filters.delivery_type ?? ''}
            options={DELIVERY_OPTIONS}
            onChange={(v) =>
              setFilters((f) => ({ ...f, delivery_type: (v || undefined) as 'native' | 'scorm' }))
            }
          />

          <DateField
            label={t('trainingLog.filter.dateFrom')}
            value={filters.date_from ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, date_from: v || undefined }))}
          />
          <DateField
            label={t('trainingLog.filter.dateTo')}
            value={filters.date_to ?? ''}
            onChange={(v) => setFilters((f) => ({ ...f, date_to: v || undefined }))}
          />
        </CardContent>
      </Card>

      {/* Summary */}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <div>
          {t('trainingLog.summary.total', { count: total })}
        </div>
        <div className="flex items-center gap-2">
          <span>{t('trainingLog.summary.showing', { from: items.length ? offset + 1 : 0, to: offset + items.length })}</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            {t('common.back')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!page || offset + limit >= total || loading}
            onClick={() => setOffset(offset + limit)}
          >
            {t('common.next')}
          </Button>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {loading && !page ? (
            <div className="p-8 space-y-3">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : error ? (
            <div className="p-8 text-center text-destructive">{error}</div>
          ) : items.length === 0 ? (
            <div className="p-10 text-center">
              <p className="font-medium text-foreground">{t('trainingLog.empty')}</p>
              <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
                {hasActiveFilters ? t('trainingLog.emptyFilteredHint') : t('trainingLog.emptyHint')}
              </p>
              {hasActiveFilters && (
                <Button type="button" variant="outline" className="mt-4" onClick={resetFilters}>
                  {t('trainingLog.filters.reset')}
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="divide-y divide-border md:hidden" data-testid="training-log-mobile-list">
                {items.map((row, idx) => (
                  <article key={`${row.user_id}-${row.course_id}-${idx}`} className="space-y-3 p-4">
                    <div>
                      <h2 className="font-medium text-foreground">{row.full_name}</h2>
                      <button type="button" className="mt-1 text-left text-sm text-primary hover:underline" onClick={() => router.push(`/courses/${row.course_id}`)}>{row.course_title}</button>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={row.computed_status === 'completed' ? 'default' : 'secondary'}>
                        {row.computed_status === 'completed' ? t('trainingLog.badge.completed') : row.computed_status === 'in_progress' ? t('trainingLog.badge.inProgress') : t('trainingLog.badge.assigned')}
                      </Badge>
                      <span className="text-sm tabular-nums text-muted-foreground">{t('trainingLog.table.progress')}: {row.progress_percent}%</span>
                    </div>
                  </article>
                ))}
              </div>
              <div className="hidden overflow-x-auto md:block">
              <Table>
                <thead className="sticky top-0 z-10 bg-card">
                  <tr className="text-left text-xs font-medium text-muted-foreground">
                    <th className={columnClass.fullName}>{t('trainingLog.table.fullName')}</th>
                    <th className={columnClass.personnelNumber}>{t('trainingLog.table.personnelNumber')}</th>
                    <th className={columnClass.department}>{t('trainingLog.table.department')}</th>
                    <th className={columnClass.position}>{t('trainingLog.table.position')}</th>
                    <th className={columnClass.course}>{t('trainingLog.table.course')}</th>
                    <th className={columnClass.type}>{t('trainingLog.table.type')}</th>
                    <th className={columnClass.status}>{t('trainingLog.table.status')}</th>
                    <th className={columnClass.progress}>{t('trainingLog.table.progress')}</th>
                    <th className={columnClass.score}>{t('trainingLog.table.score')}</th>
                    <th className={columnClass.completedAt}>{t('trainingLog.table.completedAt')}</th>
                    <th className={columnClass.certificate}>{t('trainingLog.table.certificate')}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, idx) => (
                    <tr key={`${row.user_id}-${row.course_id}-${idx}`} className="border-t border-border">
                      <td className={columnClass.fullName}>
                        <div className="font-medium text-foreground">{row.full_name}</div>
                        {row.email && (
                          <div className="text-xs text-muted-foreground">{row.email}</div>
                        )}
                      </td>
                      <td className={`${columnClass.personnelNumber} text-sm text-muted-foreground`}>
                        {row.personnel_number || '—'}
                      </td>
                      <td className={`${columnClass.department} text-sm`}>{row.department_name || '—'}</td>
                      <td className={`${columnClass.position} text-sm`}>{row.position_name || '—'}</td>
                      <td className={columnClass.course}>
                        <button
                          type="button"
                          className="text-left text-sm text-primary hover:underline"
                          onClick={() => router.push(`/courses/${row.course_id}`)}
                        >
                          {row.course_title}
                        </button>
                      </td>
                      <td className={columnClass.type}>
                        <Badge variant={row.delivery_type === 'scorm' ? 'outline' : 'default'}>
                          {row.delivery_type === 'scorm'
                            ? t('trainingLog.badge.scorm')
                            : t('trainingLog.badge.native')}
                        </Badge>
                      </td>
                      <td className={columnClass.status}>
                        <Badge
                          variant={row.computed_status === 'completed' ? 'default' : 'secondary'}
                        >
                          {row.computed_status === 'completed'
                            ? t('trainingLog.badge.completed')
                            : row.computed_status === 'in_progress'
                              ? t('trainingLog.badge.inProgress')
                              : t('trainingLog.badge.assigned')}
                        </Badge>
                      </td>
                      <td className={`${columnClass.progress} text-sm tabular-nums`}>
                        {row.progress_percent}%
                      </td>
                      <td className={`${columnClass.score} text-sm tabular-nums`}>
                        {row.best_score !== null ? `${row.best_score}%` : '—'}
                      </td>
                      <td className={`${columnClass.completedAt} text-sm text-muted-foreground`}>
                        {row.completed_at ? formatDate(row.completed_at) : '—'}
                      </td>
                      <td className={`${columnClass.certificate} text-sm`}>
                        {row.certificate_number ? (
                          <span className="text-primary">{row.certificate_number}</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{value}</div>
      </CardContent>
    </Card>
  );
}

function SelectField(props: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">
        {props.label}
      </label>
      <select
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-full h-10 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {props.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function DateField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">
        {props.label}
      </label>
      <Input
        type="date"
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
      />
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('ru-RU', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return iso;
  }
}
