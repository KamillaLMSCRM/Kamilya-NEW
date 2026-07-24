import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('course assignment selector copy', () => {
  it.each([
    ['ru', 'Выберите курс ({count})'],
    ['en', 'Select a course ({count})'],
    ['kk', 'Курсты таңдаңыз ({count})'],
  ])('uses a semantic localized course selector label for %s', (locale, expected) => {
    const messages = JSON.parse(
      readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8'),
    );

    expect(messages.courses.selectCourseCount).toBe(expected);
  });
});
