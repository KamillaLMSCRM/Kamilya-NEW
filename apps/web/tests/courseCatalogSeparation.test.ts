import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/app/courses/page.tsx'), 'utf8');

describe('course catalog hierarchy', () => {
  it('gives tenant courses an explicit landmark after the optional templates section', () => {
    expect(source).toContain('aria-labelledby="my-courses-title"');
    expect(source).toContain('id="my-courses-title"');
    expect(source.indexOf('id="blueprint-catalog-title"')).toBeLessThan(source.indexOf('id="my-courses-title"'));
  });

  it('uses a readable list layout and keeps status, review, and action affordances', () => {
    expect(source).toContain('role="list"');
    expect(source).toContain('role="listitem"');
    expect(source).toContain("t('courses.reviewRequired')");
    expect(source).toContain("t('common.actionsFor', { title: course.title })");
    expect(source).toContain("t('courses.noCourses')");
  });
});
