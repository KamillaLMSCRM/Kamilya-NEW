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

export type TranslationKey = NestedKeyOf<typeof ru>;

export function useT() {
  const lang = useLanguageStore((s) => s.lang);

  const t = useCallback(
    (key: TranslationKey): string => {
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
              return key;
            }
          }
          return typeof fallback === 'string' ? fallback : key;
        }
      }

      return typeof result === 'string' ? result : key;
    },
    [lang]
  );

  return { t, lang };
}
