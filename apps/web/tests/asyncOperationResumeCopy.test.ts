import { describe, expect, it } from 'vitest';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

describe('interrupted operation action', () => {
  it.each([
    ['ru', ru, 'Продолжить'],
    ['kk', kk, 'Жалғастыру'],
    ['en', en, 'Continue'],
  ])('does not promise nonexistent checkpoint reuse in %s', (_locale, messages, label) => {
    expect(messages.asyncOperation.continue).toBe(label);
  });
});
