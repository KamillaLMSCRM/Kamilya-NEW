'use client';

import { useEffect } from 'react';

import { useLanguageStore } from '@/store/languageStore';

export function LocaleDocumentSync() {
  const lang = useLanguageStore((state) => state.lang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return null;
}
