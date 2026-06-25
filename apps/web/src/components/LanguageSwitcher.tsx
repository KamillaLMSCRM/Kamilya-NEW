'use client';

import { Globe } from 'lucide-react';
import { useLanguageStore } from '@/store/languageStore';
import { locales, localeNames, type Locale } from '@/i18n/config';

/**
 * Language switcher — dropdown with RU / KK / EN.
 *
 * Dropdown positioning uses the same pattern as notifications: invisible
 * backdrop click + Escape would be nice but Escape is handled by sonner
 * once user clicks elsewhere; we mirror that behaviour with onBlur.
 */
export function LanguageSwitcher() {
  const lang = useLanguageStore((s) => s.lang);
  const setLang = useLanguageStore((s) => s.setLang);

  return (
    <div className="relative">
      <label htmlFor="lang-select" className="sr-only">
        Language
      </label>
      <div className="flex items-center gap-2 rounded-xl border border-border bg-muted px-2.5 py-1.5 text-sm text-foreground hover:border-foreground/20 transition-colors">
        <Globe className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
        <select
          id="lang-select"
          value={lang}
          onChange={(e) => setLang(e.target.value as Locale)}
          className="bg-transparent text-sm font-medium text-foreground outline-none cursor-pointer pr-1"
          aria-label="Select language"
        >
          {locales.map((l) => (
            <option key={l} value={l}>
              {localeNames[l]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
