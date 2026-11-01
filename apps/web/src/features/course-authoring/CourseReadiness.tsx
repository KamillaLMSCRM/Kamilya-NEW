import { authorWorkspaceCopy } from './authorWorkspaceCopy';

export function CourseReadiness({ lang, moduleCount, lessonCount, dirty, requiresReview, reviewStatus, unavailable }: {
  lang?: string; moduleCount: number; lessonCount: number; dirty: boolean; requiresReview: boolean; reviewStatus: string; unavailable: boolean;
}) {
  const copy = authorWorkspaceCopy(lang);
  const review = unavailable ? copy.unavailable : !requiresReview ? copy.notRequired
    : reviewStatus === 'approved' ? copy.approved : reviewStatus === 'needs_changes' ? copy.needsChanges
      : reviewStatus === 'pending' ? copy.pending : copy.unavailable;
  return <section aria-labelledby="author-readiness-heading" className="space-y-4 rounded-lg border border-border bg-card p-4 sm:p-5">
    <div><h2 id="author-readiness-heading" className="font-semibold">{copy.readiness}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{copy.readinessHint}</p></div>
    <dl className="grid gap-4 text-sm lg:grid-cols-3">
      <div><dt className="font-medium">{copy.outline}</dt><dd className="mt-1">{unavailable ? copy.unavailable : `${copy.modules}: ${moduleCount} · ${copy.lessons}: ${lessonCount}`}</dd>
        <dd className="mt-1 text-xs leading-5 text-muted-foreground">{copy.outlineHint}</dd></div>
      <div><dt className="font-medium">{copy.changes}</dt><dd className={`mt-1 ${dirty ? 'text-amber-700' : 'text-muted-foreground'}`}>{dirty ? copy.unsaved : copy.saved}</dd></div>
      <div><dt className="font-medium">{copy.review}</dt><dd className="mt-1">{review}</dd></div>
    </dl>
    <p className="text-xs leading-5 text-muted-foreground">{copy.approvalHint}</p>
  </section>;
}
