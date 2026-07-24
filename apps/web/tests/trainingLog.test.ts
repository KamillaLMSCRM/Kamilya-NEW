import { describe, expect, it } from 'vitest';
import { buildTrainingLogFilterQuery, buildTrainingLogPageQuery } from '@/app/admin/training-log/query';
import { interpolate } from '@/i18n/useT';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';
import fs from 'node:fs';
import path from 'node:path';
import { TRAINING_LOG_COLUMN_CLASS } from '@/app/admin/training-log/presentation';

describe('training-log request and count text', () => {
  it('sends a trimmed search term to table, summary, and CSV-compatible filters', () => {
    const filters = { status: 'assigned' as const, delivery_type: 'native' as const };

    expect(buildTrainingLogFilterQuery(filters, '  QA-UX-20260723-001  ').toString())
      .toBe('status=assigned&delivery_type=native&search=QA-UX-20260723-001');
    expect(buildTrainingLogPageQuery(filters, '  QA-UX-20260723-001  ', 100, 0))
      .toBe('status=assigned&delivery_type=native&search=QA-UX-20260723-001&limit=100&offset=0');
  });

  it.each([
    [ru, 'Всего записей: 2', 'Показаны 1–2'],
    [kk, 'Барлығы: 2', '1–2 көрсетілді'],
    [en, 'Total rows: 2', 'Showing 1–2'],
  ])('renders concrete count and pagination text for each locale', (locale, total, showing) => {
    expect(interpolate(locale.trainingLog.summary.total, { count: 2 })).toBe(total);
    expect(interpolate(locale.trainingLog.summary.showing, { from: 1, to: 2 })).toBe(showing);
  });
});

describe('training-log responsive presentation', () => {
  it('keeps a mobile card list and a sticky desktop table header', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );

    expect(source).toContain('data-testid="training-log-mobile-list"');
    expect(source).toContain('md:hidden');
    expect(source).toContain('hidden overflow-x-auto md:block');
    expect(source).toContain('sticky top-0');
  });

  it('uses one named visibility contract for table headers and cells', () => {
    const tabletColumns = ['fullName', 'course', 'status', 'progress'] as const;
    const desktopOnlyColumns = [
      'personnelNumber',
      'department',
      'position',
      'type',
      'score',
      'completedAt',
      'certificate',
    ] as const;

    tabletColumns.forEach((column) => {
      expect(TRAINING_LOG_COLUMN_CLASS[column]).not.toContain('hidden');
    });
    desktopOnlyColumns.forEach((column) => {
      expect(TRAINING_LOG_COLUMN_CLASS[column]).toContain('hidden');
      expect(TRAINING_LOG_COLUMN_CLASS[column]).toContain('lg:table-cell');
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
