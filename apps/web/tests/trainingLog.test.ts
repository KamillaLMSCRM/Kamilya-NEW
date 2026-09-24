import { describe, expect, it } from 'vitest';
import {
  buildTrainingLogBrowserHref,
  buildTrainingLogFilterQuery,
  buildTrainingLogPageQuery,
  parseTrainingLogBrowserQuery,
} from '@/app/admin/training-log/query';
import { interpolate } from '@/i18n/useT';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';
import fs from 'node:fs';
import path from 'node:path';
import { TRAINING_LOG_COLUMN_CLASS } from '@/app/admin/training-log/presentation';

describe('training-log request and count text', () => {
  it('round-trips only the supported browser filters and a safe dashboard return path', () => {
    const href = buildTrainingLogBrowserHref({
      filters: {
        enrollment_id: '11111111-1111-4111-8111-111111111111',
        course_id: '22222222-2222-4222-8222-222222222222',
        status: 'overdue',
        history: true,
      },
      search: '  learner  ',
      returnTo: '/dashboard',
    });

    expect(href).toBe('/training-log?enrollment_id=11111111-1111-4111-8111-111111111111&course_id=22222222-2222-4222-8222-222222222222&status=overdue&history=true&search=learner&return_to=%2Fdashboard');
    expect(parseTrainingLogBrowserQuery(new URLSearchParams(href.split('?')[1]))).toEqual({
      filters: {
        enrollment_id: '11111111-1111-4111-8111-111111111111',
        course_id: '22222222-2222-4222-8222-222222222222',
        status: 'overdue',
        history: true,
      },
      search: 'learner',
      returnTo: '/dashboard',
    });
  });

  it('drops malformed filters, API-only parameters, and unsafe return targets', () => {
    const parsed = parseTrainingLogBrowserQuery(new URLSearchParams({
      enrollment_id: 'not-a-uuid',
      status: 'failed',
      delivery_type: 'video',
      date_from: 'not-a-date',
      limit: '500',
      format: 'csv',
      return_to: '//evil.example/path',
      search: ' x '.repeat(120),
    }));

    expect(parsed).toEqual({ filters: {}, search: '', returnTo: null });
  });

  it('sends a trimmed search term to table, summary, and CSV-compatible filters', () => {
    const filters = { status: 'assigned' as const, delivery_type: 'native' as const };

    expect(buildTrainingLogFilterQuery(filters, '  QA-UX-20260723-001  ').toString())
      .toBe('status=assigned&delivery_type=native&search=QA-UX-20260723-001');
    expect(buildTrainingLogPageQuery(filters, '  QA-UX-20260723-001  ', 100, 0))
      .toBe('status=assigned&delivery_type=native&search=QA-UX-20260723-001&limit=100&offset=0');
    expect(buildTrainingLogFilterQuery({ status: 'overdue' }, '').toString())
      .toBe('status=overdue');
  });

  it('passes an exact enrollment occurrence to table and summary queries', () => {
    expect(buildTrainingLogFilterQuery({ enrollment_id: '11111111-1111-4111-8111-111111111111' }, '').toString())
      .toBe('enrollment_id=11111111-1111-4111-8111-111111111111');
  });

  it('requests historical enrollment rows only when explicitly enabled', () => {
    expect(buildTrainingLogFilterQuery({ history: true }, '').toString()).toBe('history=true');
    expect(buildTrainingLogFilterQuery({}, '').toString()).toBe('');
  });

  it.each([
    [ru, 'Всего записей: 2', 'Показаны 1–2'],
    [kk, 'Барлығы: 2', '1–2 көрсетілді'],
    [en, 'Total rows: 2', 'Showing 1–2'],
  ])('renders concrete count and pagination text for each locale', (locale, total, showing) => {
    expect(interpolate(locale.trainingLog.summary.total, { count: 2 })).toBe(total);
    expect(interpolate(locale.trainingLog.summary.showing, { from: 1, to: 2 })).toBe(showing);
  });

  it.each([ru, kk, en])('separates completion certificates from documentary evidence confirmation', (locale) => {
    const evidence = locale.trainingLog.evidence as unknown as Record<string, string>;
    expect(evidence.pending).toBeTruthy();
    expect(evidence.certificateIndependent).toBeTruthy();
    expect(evidence.unavailable).not.toMatch(/certificate|сертификат|сертификат/i);
  });

  it.each([ru, kk, en])('labels recurring deadlines and overdue attention consistently', (locale) => {
    expect(locale.trainingLog.filter.status.overdue).toBeTruthy();
    expect(locale.trainingLog.table.deadline).toBeTruthy();
    expect(locale.trainingLog.badge.deadlineOverdue).toBeTruthy();
    expect(locale.trainingLog.badge.completedLate).toBeTruthy();
  });

  it.each([ru, kk, en])('labels certificate validity independently from evidence', (locale) => {
    expect(locale.trainingLog.table.certificateValidUntil).toBeTruthy();
    expect(locale.trainingLog.badge.certificateActive).toBeTruthy();
    expect(locale.trainingLog.badge.certificateExpiring).toBeTruthy();
    expect(locale.trainingLog.badge.certificateExpired).toBeTruthy();
    expect(locale.trainingLog.badge.certificateRevoked).toBeTruthy();
  });

  it.each([ru, kk, en])('labels historical lifecycle states explicitly', (locale) => {
    expect(locale.trainingLog.history.include).toBeTruthy();
    expect(locale.trainingLog.history.cancelled).toBeTruthy();
    expect(locale.trainingLog.history.superseded).toBeTruthy();
  });
});

describe('training-log ownership', () => {
  it('uses one canonical read-only reporting screen and keeps evidence actions methodologist-only', () => {
    const source = fs.readFileSync(path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'), 'utf8');
    expect(source).toContain('user?.role === \'methodologist\'');
  });
});

describe('training-log responsive presentation', () => {
  it('keeps a mobile card list and a sticky desktop table header', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );

    expect(source).toContain('data-testid="training-log-mobile-list"');
    expect(source).toContain('lg:hidden');
    expect(source).toContain('tableClassName="w-max min-w-[2340px]"');
    expect(source).toContain('training-log-table-scroll');
    expect(source).toContain('sticky top-0');
    expect(TRAINING_LOG_COLUMN_CLASS.fullName).toContain('sticky left-0');
    expect(source).toContain('<DeadlineStatusBadge row={row} t={t} />');
  });

  it('shows the returned signed-scan workflow in both responsive presentations for eligible evidence', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );

    expect(source).toContain('useSignedScanLedgers');
    expect(source).toContain('canAttachSignedScan(row)');
    expect(source.match(/signedScanControl\(row\.latest_evidence_event_id/g)).toHaveLength(2);
  });

  it('uses one named width contract for table headers and cells', () => {
    const columns = [
      'fullName',
      'course',
      'status',
      'deadline',
      'progress',
      'personnelNumber',
      'department',
      'position',
      'type',
      'source',
      'score',
      'completedAt',
      'certificate',
    ] as const;

    columns.forEach((column) => {
      expect(TRAINING_LOG_COLUMN_CLASS[column]).toContain('min-w-');
      expect(TRAINING_LOG_COLUMN_CLASS[column]).not.toContain('hidden');
    });

    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );
    Object.keys(TRAINING_LOG_COLUMN_CLASS).forEach((column) => {
      expect(source.match(new RegExp(`columnClass\\.${column}`, 'g'))).toHaveLength(2);
    });
  });
});
