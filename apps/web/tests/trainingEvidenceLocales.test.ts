import { describe, expect, it } from "vitest";

import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

type JsonObject = Record<string, unknown>;

const locales = { ru, kk, en } as const;
const sections = ['trainingProceduresPage', 'trainingRetentionPage'] as const;

function leafKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [prefix];
  return Object.entries(value as JsonObject).flatMap(([key, child]) => leafKeys(child, prefix ? `${prefix}.${key}` : key));
}

function leafStrings(value: unknown, prefix = ''): Array<[string, string]> {
  if (typeof value === 'string') return [[prefix, value]];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as JsonObject).flatMap(([key, child]) => leafStrings(child, prefix ? `${prefix}.${key}` : key));
}

const englishPlaceholder = /^(?:Configure |No (?:procedures|retention)|New |Create |Edit(?: |$)|Stable |Procedure |Confirmation |Retention |Evidence |Legal |Internal |Acknowledgement|Admission |Manual |Email |One-time |Could |This |Draft|Active|Retired|Preview|Execution|Policy|Training|Knowledge|Separate |Commission |Authorized |Effective|Approval |Name$|Description$|Version$|Type$|Quorum$|Record$|Rule$|Days$|Activate$|Retire$|Purge|Delete |Run |The |Add |Cannot |Available|Section|Action)/i;

describe('training procedure and retention translations', () => {
  it('keeps the two section structures identical in ru, kk and en', () => {
    for (const section of sections) {
      const expected = leafKeys(locales.en[section]);
      expect(leafKeys(locales.ru[section]), section).toEqual(expected);
      expect(leafKeys(locales.kk[section]), section).toEqual(expected);
    }
  });

  it('does not leave English placeholder strings in Russian or Kazakh', () => {
    for (const locale of ['ru', 'kk'] as const) {
      for (const section of sections) {
        for (const [key, value] of leafStrings(locales[locale][section])) {
          expect(value, `${locale}.${section}.${key}`).not.toMatch(englishPlaceholder);
        }
      }
    }
  });

  it('exposes only confirmation methods implemented by the UI', () => {
    for (const locale of Object.values(locales)) {
      expect(Object.keys(locale.trainingProceduresPage.confirmations).sort()).toEqual(['email_otp', 'manual_record']);
    }
  });
});
