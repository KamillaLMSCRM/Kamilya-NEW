import { useId, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowRight, ChevronRight } from 'lucide-react';

export type DashboardTask = {
  id: string;
  title: string;
  subtitle: string;
  status: string;
  details: { label: string; value: string }[];
  href: string;
  action: string;
};

type TaskGroup = {
  id: string;
  title: string;
  empty: string;
  tasks: DashboardTask[];
  notice?: string;
  link?: { href: string; label: string };
};

const messages = {
  ru: { queue: 'Рабочие задачи', details: 'Детали задачи', choose: 'Выберите задачу из списка.', empty: 'Нет доступных задач для просмотра.', next: 'Следующее действие', back: 'К выбранной задаче' },
  kk: { queue: 'Жұмыс тапсырмалары', details: 'Тапсырма мәліметтері', choose: 'Тізімнен тапсырманы таңдаңыз.', empty: 'Көруге қолжетімді тапсырмалар жоқ.', next: 'Келесі әрекет', back: 'Таңдалған тапсырмаға' },
  en: { queue: 'Work queue', details: 'Task details', choose: 'Select a task from the list.', empty: 'No tasks are available to view.', next: 'Next action', back: 'Back to selected task' },
} as const;

export function DashboardTaskQueue({ groups, lang }: { groups: TaskGroup[]; lang: string }) {
  const copy = lang === 'kk' ? messages.kk : lang === 'en' ? messages.en : messages.ru;
  const id = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const tasks = groups.flatMap((group) => group.tasks);
  const selected = tasks.find((task) => task.id === selectedId) ?? tasks[0];
  const panel = useRef<HTMLElement>(null);
  const activeRow = useRef<HTMLButtonElement | null>(null);

  function select(task: DashboardTask, button: HTMLButtonElement) {
    setSelectedId(task.id);
    activeRow.current = button;
    // When stacked, bring the details into view and make them the next keyboard stop.
    if (window.matchMedia?.('(max-width: 1023px)').matches) {
      window.requestAnimationFrame(() => panel.current?.focus());
    }
  }

  return (
    <div className="methodologist-split">
      <section aria-labelledby={`${id}-queue`} className="min-w-0 rounded-2xl border border-border bg-card p-4 sm:p-5">
        <h2 id={`${id}-queue`} className="text-lg font-semibold">{copy.queue}</h2>
        {groups.map((group) => (
          <div key={group.id} className="mt-4 border-t border-border pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{group.title}</h3>
              {group.link && <Link href={group.link.href} className="inline-flex min-h-8 items-center rounded text-sm font-medium text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring">{group.link.label}</Link>}
            </div>
            {group.tasks.length ? <ul className="mt-2 space-y-1.5">
              {group.tasks.map((task) => {
                const pressed = selected?.id === task.id;
                return <li key={task.id}>
                  <button type="button" aria-pressed={pressed} aria-controls={`${id}-details`}
                    onClick={(event) => select(task, event.currentTarget)}
                    className={`flex min-h-12 w-full min-w-0 items-center gap-3 rounded-xl border px-3 py-2 text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${pressed ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted'}`}>
                    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                      <span className="block text-sm font-medium">{task.title}</span>
                      <span className="block text-xs text-muted-foreground">{task.subtitle}</span>
                    </span>
                    <span className="max-w-[38%] rounded-md bg-muted px-2 py-1 text-xs text-foreground [overflow-wrap:anywhere]">{task.status}</span>
                    <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                  </button>
                </li>;
              })}
            </ul> : <p className="mt-2 text-sm text-muted-foreground">{group.empty}</p>}
            {group.notice && <p className="mt-2 text-xs text-muted-foreground">{group.notice}</p>}
          </div>
        ))}
      </section>
      <section ref={panel} id={`${id}-details`} tabIndex={-1} aria-labelledby={`${id}-details-heading`}
        className="min-w-0 scroll-mt-28 rounded-2xl border border-border bg-card p-4 [overflow-wrap:anywhere] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-5 lg:sticky lg:top-24">
        <h2 id={`${id}-details-heading`} className="text-lg font-semibold">{copy.details}</h2>
        <p aria-live="polite" className="sr-only">{selected ? `${selected.title} — ${selected.status}` : ''}</p>
        {selected ? <>
          <h3 className="mt-3 font-semibold">{selected.title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{selected.subtitle}</p>
          <dl className="mt-4 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
            {selected.details.map(({ label, value }) => <div key={label} className="text-sm">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium">{value}</dd>
            </div>)}
          </dl>
          <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-3">
            <h4 className="text-sm font-semibold">{copy.next}</h4>
            <Link href={selected.href} className="mt-2 inline-flex min-h-10 max-w-full items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              {selected.action}<ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />
            </Link>
          </div>
          <button type="button" onClick={() => activeRow.current?.focus()} className="mt-3 min-h-10 rounded text-sm text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring lg:hidden">{copy.back}</button>
        </> : <p className="mt-3 text-sm text-muted-foreground">{groups.some((group) => group.tasks.length) ? copy.choose : copy.empty}</p>}
      </section>
    </div>
  );
}
