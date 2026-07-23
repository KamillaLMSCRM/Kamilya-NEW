import { describe, expect, it } from 'vitest';
import { buildTrainingLogFilterQuery, buildTrainingLogPageQuery } from '@/app/admin/training-log/query';
import { interpolate } from '@/i18n/useT';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

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
