'use client';

import Link from 'next/link';
import { useT } from '@/i18n/useT';

export function PublicLegalFooter() {
  const { t } = useT();
  return (
    <footer className="mx-auto mt-6 w-full max-w-6xl px-4 pb-4 text-center text-xs text-muted-foreground">
      <p>{t('publicUi.legal.operator')}</p>
      <p className="mt-1"><a href="mailto:askar@kml.kz" className="underline-offset-4 hover:text-foreground hover:underline">askar@kml.kz</a> · <a href="tel:+77072750007" className="underline-offset-4 hover:text-foreground hover:underline">+7 707 275 0007</a></p>
      <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-2">
      <Link href="/legal/privacy" className="underline-offset-4 hover:text-foreground hover:underline">{t('publicUi.legal.privacy')}</Link>
      <Link href="/legal/terms" className="underline-offset-4 hover:text-foreground hover:underline">{t('publicUi.legal.terms')}</Link>
      <Link href="/legal/privacy/kk" className="underline-offset-4 hover:text-foreground hover:underline">{t('publicUi.legal.kazakhVersion')}</Link>
      </div>
    </footer>
  );
}
