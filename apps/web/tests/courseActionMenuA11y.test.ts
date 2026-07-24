import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('course secondary action menu accessibility', () => {
  it('names the menu for the specific course in every locale', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/courses/page.tsx'), 'utf8');
    expect(source).toContain("t('common.actionsFor', { title: course.title })");

    for (const locale of ['ru', 'en', 'kk']) {
      const messages = JSON.parse(
        readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8'),
      );
      expect(messages.common.actionsFor).toContain('{title}');
    }
  });
});
