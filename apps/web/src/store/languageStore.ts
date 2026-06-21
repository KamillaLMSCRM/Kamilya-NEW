import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Locale } from '@/i18n/config';

interface LanguageState {
  lang: Locale;
  setLang: (lang: Locale) => void;
}

export const useLanguageStore = create<LanguageState>()(
  persist(
    (set) => ({
      lang: 'ru',
      setLang: (lang) => set({ lang }),
    }),
    { name: 'kamilya-language' }
  )
);
