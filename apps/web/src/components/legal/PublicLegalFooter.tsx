import Link from 'next/link';

export function PublicLegalFooter() {
  return (
    <footer className="mx-auto mt-6 w-full max-w-6xl px-4 pb-4 text-center text-xs text-muted-foreground">
      <p>ТОО «Document. KZ» · БИН 080340022947 · Казахстан, город Алматы, Бостандыкский район, улица Радостовца, дом 152Л, 050060</p>
      <p className="mt-1"><a href="mailto:askar@kml.kz" className="underline-offset-4 hover:text-foreground hover:underline">askar@kml.kz</a> · <a href="tel:+77072750007" className="underline-offset-4 hover:text-foreground hover:underline">+7 707 275 0007</a></p>
      <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-2">
      <Link href="/legal/privacy" className="underline-offset-4 hover:text-foreground hover:underline">Уведомление о конфиденциальности</Link>
      <Link href="/legal/terms" className="underline-offset-4 hover:text-foreground hover:underline">Условия сайта и пробного доступа</Link>
      <Link href="/legal/privacy/kk" className="underline-offset-4 hover:text-foreground hover:underline">Қазақша</Link>
      </div>
    </footer>
  );
}
