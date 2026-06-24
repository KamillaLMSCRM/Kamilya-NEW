'use client';

import { useT } from '@/i18n/useT';

/**
 * Skip-to-content link: visible only when focused (keyboard users).
 * Pinned to the top of the page; clicking jumps focus to #main-content.
 *
 * Pages should mark their main container with id="main-content" + tabIndex={-1}.
 */
export function SkipToContent() {
  const { t } = useT();
  return (
    <a
      href="#main-content"
      className="
        sr-only focus:not-sr-only
        focus:fixed focus:top-2 focus:left-2 focus:z-[100]
        focus:px-4 focus:py-2 focus:rounded-md
        focus:bg-primary focus:text-primary-foreground
        focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-ring
      "
    >
      {t('a11y.skipToContent')}
    </a>
  );
}
