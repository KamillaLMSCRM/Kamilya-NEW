interface CourseProvenanceProps {
  authorName?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  lang: string;
}

const labels = {
  ru: { author: 'Автор', created: 'Создан', updated: 'Изменён', unknown: 'Не указан', noDate: 'Нет данных' },
  kk: { author: 'Автор', created: 'Жасалған', updated: 'Өзгертілген', unknown: 'Көрсетілмеген', noDate: 'Дерек жоқ' },
  en: { author: 'Author', created: 'Created', updated: 'Updated', unknown: 'Not recorded', noDate: 'Not recorded' },
};

export function CourseProvenance({ authorName, createdAt, updatedAt, lang }: CourseProvenanceProps) {
  const text = labels[lang as keyof typeof labels] ?? labels.ru;
  const locale = lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-GB' : 'ru-RU';
  const date = (value?: string | null) => {
    if (!value || !Number.isFinite(Date.parse(value))) return text.noDate;
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Almaty' }).format(new Date(value));
  };
  return <dl aria-label={text.author} className="mt-3 grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
    <div className="sm:col-span-2"><dt className="inline">{text.author}: </dt><dd className="inline text-foreground">{authorName?.trim() || text.unknown}</dd></div>
    <div><dt className="inline">{text.created}: </dt><dd className="inline">{date(createdAt)}</dd></div>
    <div><dt className="inline">{text.updated}: </dt><dd className="inline">{date(updatedAt)}</dd></div>
  </dl>;
}
