import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import en from '@/i18n/locales/en.json';
import kk from '@/i18n/locales/kk.json';
import ru from '@/i18n/locales/ru.json';

const blueprintPage = readFileSync(
  resolve(process.cwd(), 'src/app/courses/templates/[blueprintId]/page.tsx'),
  'utf8',
);
const coursesPage = readFileSync(resolve(process.cwd(), 'src/app/courses/page.tsx'), 'utf8');

const leafKeys = (value: unknown, prefix = ''): string[] => {
  if (!value || typeof value !== 'object') return [prefix];
  return Object.entries(value as Record<string, unknown>)
    .flatMap(([key, child]) => leafKeys(child, prefix ? `${prefix}.${key}` : key))
    .sort();
};

describe('finance course blueprint contract', () => {
  it('keeps blueprint copy shape identical in every LMS locale', () => {
    expect(leafKeys(kk.courses.blueprint)).toEqual(leafKeys(ru.courses.blueprint));
    expect(leafKeys(en.courses.blueprint)).toEqual(leafKeys(ru.courses.blueprint));
  });

  it('uses the tenant-safe catalogue and adaptation endpoints', () => {
    expect(blueprintPage).toContain('/v1/course-blueprints/');
    expect(blueprintPage).toContain('/blueprint-adaptation');
    expect(blueprintPage).toContain('source_document_ids');
    expect(blueprintPage).toContain('isDocumentSelectable');
  });

  it('exposes the finance template from the canonical courses screen', () => {
    expect(coursesPage).toContain('/courses/templates/kz-finance-information-security');
    expect(coursesPage).toContain("course.source_analysis?.blueprint?.id");
  });

  it('shows legal limitations before the save action', () => {
    expect(blueprintPage.indexOf('blueprint.limitations')).toBeLessThan(
      blueprintPage.indexOf('onClick={save}'),
    );
  });
});
