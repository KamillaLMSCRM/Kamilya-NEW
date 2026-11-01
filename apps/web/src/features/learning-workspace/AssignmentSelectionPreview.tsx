import { CheckCircle2, Users } from 'lucide-react';
import { workspaceCopy } from './copy';

/** Describes selected inputs, not a server-issued authorization or frozen plan. */
export function AssignmentSelectionPreview({ lang, courseTitle, names, existingCount, completedCount, deliveryLabel }: {
  lang: string; courseTitle?: string; names: string[];
  existingCount: number | null; completedCount: number | null; deliveryLabel: string;
}) {
  const m = workspaceCopy(lang);
  return <section className="min-w-0 rounded-xl border border-primary/20 bg-primary/5 p-4" aria-label={m.assignmentTitle}>
    <h3 className="flex items-center gap-2 text-sm font-semibold"><Users className="h-4 w-4 text-primary" aria-hidden="true" />{m.assignmentTitle}</h3>
    <p className="mt-2 break-words text-sm font-medium">{courseTitle || m.noCourse}</p>
    <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
      <div className="rounded-lg bg-card p-2"><dt className="text-muted-foreground">{m.selected}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{names.length}</dd></div>
      <div className="rounded-lg bg-card p-2"><dt className="text-muted-foreground">{m.existing}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{existingCount ?? '—'}</dd></div>
      <div className="rounded-lg bg-card p-2"><dt className="text-muted-foreground">{m.completed}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{completedCount ?? '—'}</dd></div>
    </dl>
    {names.length > 0 && <details className="mt-3 rounded-lg border border-border bg-card p-3" open={names.length <= 5}>
      <summary className="cursor-pointer text-xs font-semibold">{m.recipients} ({names.length})</summary>
      <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-sm">{names.map((name, index) => <li key={index} className="break-words">{name}</li>)}</ul>
    </details>}
    <p className="mt-3 text-xs text-muted-foreground">{m.delivery}: {deliveryLabel}</p>
    <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-muted-foreground"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />{m.assignmentHint}</p>
    <p className="mt-2 text-xs leading-5 text-muted-foreground">{m.confirmNote}</p>
  </section>;
}
