import { describe, expect, it } from 'vitest';

import { interpolate, selectPluralForm } from '@/i18n/useT';

const lessonForms = {
  one: '{count} урок',
  few: '{count} урока',
  many: '{count} уроков',
  other: '{count} урока',
};

const lessonTotalForms = {
  one: '{count} урока',
  few: '{count} уроков',
  many: '{count} уроков',
  other: '{count} уроков',
};

describe('Russian pluralization', () => {
  it.each([
    [0, '0 уроков'],
    [1, '1 урок'],
    [2, '2 урока'],
    [4, '4 урока'],
    [5, '5 уроков'],
    [11, '11 уроков'],
    [21, '21 урок'],
    [22, '22 урока'],
    [25, '25 уроков'],
  ])('formats %i correctly', (count, expected) => {
    const template = selectPluralForm(lessonForms, count, 'ru');
    expect(interpolate(template, { count })).toBe(expected);
  });

  it('uses the English one/other categories', () => {
    const forms = {
      one: '{count} lesson',
      few: '{count} lessons',
      many: '{count} lessons',
      other: '{count} lessons',
    };

    expect(interpolate(selectPluralForm(forms, 1, 'en'), { count: 1 })).toBe('1 lesson');
    expect(interpolate(selectPluralForm(forms, 2, 'en'), { count: 2 })).toBe('2 lessons');
  });

  it.each([
    [1, '1 урока'],
    [2, '2 уроков'],
    [5, '5 уроков'],
    [21, '21 урока'],
    [22, '22 уроков'],
  ])('formats denominator %i correctly', (count, expected) => {
    const template = selectPluralForm(lessonTotalForms, count, 'ru');
    expect(interpolate(template, { count })).toBe(expected);
  });
});
