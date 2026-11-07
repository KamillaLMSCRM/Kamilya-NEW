'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { AuthenticatedSourceImage } from '@/components/AuthenticatedSourceImage';
import { WorkspacePanel } from '@/features/workspace-design';
import type { SourcePreparation } from './contract';

const labels = {
  ru: { title: 'Части документа', hint: 'Выберите материалы для обучения и примените выбор. Проверка начнётся заново.', apply: 'Применить выбор', reset: 'Сверить с текущим документом', stale: 'Документ изменился. Сверьте выбор с текущей версией.', pages: 'Страницы', figures: 'Иллюстрации', loading: 'Загрузка изображения…', error: 'Не удалось загрузить изображение', open: 'Открыть изображение в полном размере', roles: { learning: 'Обучение', supporting: 'Дополнение', administrative: 'Административная часть' } },
  kk: { title: 'Құжат бөліктері', hint: 'Оқыту материалдарын таңдап, таңдауды қолданыңыз. Тексеру қайта басталады.', apply: 'Таңдауды қолдану', reset: 'Ағымдағы құжатпен салыстыру', stale: 'Құжат өзгерді. Таңдауды ағымдағы нұсқамен салыстырыңыз.', pages: 'Беттер', figures: 'Суреттер', loading: 'Сурет жүктелуде…', error: 'Суретті жүктеу мүмкін болмады', open: 'Суретті толық өлшемде ашу', roles: { learning: 'Оқыту', supporting: 'Қосымша', administrative: 'Әкімшілік бөлік' } },
  en: { title: 'Document parts', hint: 'Select the learning material and apply your selection. Review will start again.', apply: 'Apply selection', reset: 'Compare with current document', stale: 'The document changed. Compare your selection with the current version.', pages: 'Pages', figures: 'Illustrations', loading: 'Loading image…', error: 'Could not load image', open: 'Open full-size image', roles: { learning: 'Learning', supporting: 'Supporting', administrative: 'Administrative' } },
};

export function SourcePreparationPanel({ preparation, lang, editable, disabled, onApply, onDraftChange }: {
  preparation: SourcePreparation; lang: string; editable: boolean; disabled: boolean;
  onApply: (ids: string[], sha256: string) => Promise<boolean>;
  onDraftChange: (dirty: boolean) => void;
}) {
  const copy = labels[lang === 'kk' || lang === 'en' ? lang : 'ru'];
  const [draft, setDraft] = useState<{ sha256: string; ids: string[] } | null>(null);
  const current = draft ?? { sha256: preparation.sha256, ids: preparation.selected_part_ids };
  const stale = current.sha256 !== preparation.sha256;
  const changed = current.ids.length !== preparation.selected_part_ids.length
    || current.ids.some(id => !preparation.selected_part_ids.includes(id));
  useEffect(() => { onDraftChange(editable && (changed || stale)); }, [changed, editable, onDraftChange, stale]);
  useEffect(() => () => onDraftChange(false), [onDraftChange]);
  return <WorkspacePanel bodyClassName="space-y-4">
    <h2 className="font-semibold">{copy.title}</h2>
    {editable && <p className="text-sm text-muted-foreground">{copy.hint}</p>}
    {stale && <div role="alert" className="space-y-2"><p>{copy.stale}</p>
      <Button variant="outline" onClick={() => setDraft(null)}>{copy.reset}</Button></div>}
    <fieldset disabled={!editable || disabled || stale} className="space-y-2">
      <legend className="sr-only">{copy.title}</legend>
      {preparation.parts.map(part => <label key={part.id} className="flex min-w-0 gap-3 rounded-lg border border-border p-3">
        <input type="checkbox" className="mt-1 shrink-0" checked={current.ids.includes(part.id)} onChange={event => setDraft({
          sha256: preparation.sha256,
          ids: event.target.checked ? [...current.ids, part.id] : current.ids.filter(id => id !== part.id),
        })} />
        <span className="min-w-0 break-words"><span className="block font-medium">{part.title}</span>
          <span className="block text-sm text-muted-foreground">{copy.roles[part.role]}{part.page_first != null ? ` · ${copy.pages} ${part.page_first}${part.page_last != null && part.page_last !== part.page_first ? `–${part.page_last}` : ''}` : ''}</span>
          <span className="block text-sm">{part.reason}</span></span>
      </label>)}
    </fieldset>
    {editable && <Button disabled={disabled || stale || !changed || current.ids.length === 0} onClick={() => void onApply(current.ids, current.sha256).then(ok => { if (ok) setDraft(null); })}>{copy.apply}</Button>}
    {preparation.assets.length > 0 && <section className="space-y-3"><h3 className="font-medium">{copy.figures}</h3>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">{preparation.assets.map(asset => <figure key={asset.id} className="min-w-0 space-y-1 rounded-lg border border-border p-3">
        <AuthenticatedSourceImage url={asset.preview_url} alt={asset.caption || copy.figures} loadingLabel={copy.loading} errorLabel={copy.error} openLabel={copy.open} />
        <figcaption className="break-words text-sm">{asset.caption}</figcaption>
      </figure>)}</div></section>}
  </WorkspacePanel>;
}
