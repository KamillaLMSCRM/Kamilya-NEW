'use client';

import { useEffect } from 'react';

import { locales, type Locale } from '@/i18n/config';
import { useLanguageStore } from '@/store/languageStore';

/** Apply an explicit cross-site locale without overriding normal persistence. */
export function useLocaleQuery() {
  const setLang = useLanguageStore((state) => state.setLang);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('lang');
    if (requested && locales.includes(requested as Locale)) {
      setLang(requested as Locale);
    }
  }, [setLang]);
}
