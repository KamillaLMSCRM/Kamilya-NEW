'use client';

import { useCallback } from 'react';
import { useLanguageStore } from '@/store/languageStore';
import ru from './locales/ru.json';
import kk from './locales/kk.json';
import en from './locales/en.json';

const translations: Record<string, typeof ru> = { ru, kk, en };

type NestedKeyOf<T> = T extends object
  ? { [K in keyof T]: K extends string ? (T[K] extends object ? `${K}.${NestedKeyOf<T[K]>}` : K) : never }[keyof T]
  : never;

type PluralForms = {
  one: string;
  few: string;
  many: string;
  other: string;
};

type PluralKeyOf<T> = T extends object
  ? {
      [K in keyof T]: K extends string
        ? T[K] extends PluralForms
          ? K
          : T[K] extends object
            ? `${K}.${PluralKeyOf<T[K]>}`
            : never
        : never;
    }[keyof T]
  : never;

export type TranslationKey = NestedKeyOf<typeof ru>;
export type PluralTranslationKey = PluralKeyOf<typeof ru>;

/** Interpolate `{key}` placeholders in a translation string. */
export function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, name) => {
    const v = params[name];
    return v === undefined ? `{${name}}` : String(v);
  });
}

export function selectPluralForm(forms: PluralForms, count: number, lang: string): string {
  const category = new Intl.PluralRules(lang).select(count);
  return forms[category as keyof PluralForms] ?? forms.other;
}

export function useT() {
  const lang = useLanguageStore((s) => s.lang);

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>): string => {
      const keys = key.split('.');
      let result: any = translations[lang] || translations.ru;

      for (const k of keys) {
        if (result && typeof result === 'object' && k in result) {
          result = result[k];
        } else {
          // Fallback to Russian
          let fallback: any = translations.ru;
          for (const fk of keys) {
            if (fallback && typeof fallback === 'object' && fk in fallback) {
              fallback = fallback[fk];
            } else {
              return interpolate(key, params);
            }
          }
          return interpolate(
            typeof fallback === 'string' ? fallback : key,
            params
          );
        }
      }

      return interpolate(typeof result === 'string' ? result : key, params);
    },
    [lang]
  );

  const tp = useCallback(
    (
      key: PluralTranslationKey,
      count: number,
      params?: Record<string, string | number>
    ): string => {
      const keys = key.split('.');
      let result: any = translations[lang] || translations.ru;

      for (const k of keys) {
        if (result && typeof result === 'object' && k in result) {
          result = result[k];
        } else {
          result = undefined;
          break;
        }
      }

      if (!result || typeof result !== 'object') {
        let fallback: any = translations.ru;
        for (const fk of keys) {
          if (fallback && typeof fallback === 'object' && fk in fallback) {
            fallback = fallback[fk];
          } else {
            return interpolate(key, { ...params, count });
          }
        }
        result = fallback;
      }

      return interpolate(
        selectPluralForm(result as PluralForms, count, lang),
        { ...params, count }
      );
    },
    [lang]
  );

  return { t, tp, lang };
}
