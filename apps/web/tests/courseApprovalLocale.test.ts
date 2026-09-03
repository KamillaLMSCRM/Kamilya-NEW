import { describe, expect, it } from 'vitest';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

describe('course approval localization', () => {
  it('keeps the approval copy contract in every supported locale', () => {
    const keys = Object.keys(ru.courseApproval);
    for (const locale of [kk, en]) {
      expect(Object.keys(locale.courseApproval)).toEqual(expect.arrayContaining(keys));
    }
  });

  it.each([ru, kk, en])('contains translated one-time credential copy', (locale) => {
    expect(locale.courseApproval.credentialsTitle).toBeTruthy();
    expect(locale.courseApproval.credentialsWarning).toBeTruthy();
    expect(locale.courseApproval.copyUrl).toBeTruthy();
    expect(locale.courseApproval.copyPin).toBeTruthy();
    expect(locale.courseApproval.credentialsAcknowledge).toBeTruthy();
  });
});
