'use client';

import { useLanguageStore } from '@/store/languageStore';
import { locales, localeNames, type Locale } from '@/i18n/config';

export default function LanguageSwitcher() {
  const { lang, setLang } = useLanguageStore();

  return (
    <select
      value={lang}
      onChange={(e) => setLang(e.target.value as Locale)}
      className="border rounded px-2 py-1 text-sm bg-white"
    >
      {locales.map((l) => (
        <option key={l} value={l}>
          {localeNames[l]}
        </option>
      ))}
    </select>
  );
}
