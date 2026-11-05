import { authorWorkspaceCopy } from './authorWorkspaceCopy';
import { WorkspacePanel } from '@/features/workspace-design';

export function CourseReadiness({ lang, moduleCount, lessonCount, dirty, requiresReview, reviewStatus, unavailable }: {
  lang?: string; moduleCount: number; lessonCount: number; dirty: boolean; requiresReview: boolean; reviewStatus: string; unavailable: boolean;
}) {
  const copy = authorWorkspaceCopy(lang);
  const review = unavailable ? copy.unavailable : !requiresReview ? copy.notRequired
    : reviewStatus === 'approved' ? copy.approved : reviewStatus === 'needs_changes' ? copy.needsChanges
      : reviewStatus === 'pending' ? copy.pending : copy.unavailable;
  return <WorkspacePanel aria-labelledby="author-readiness-heading" bodyClassName="grid gap-4 xl:grid-cols-[minmax(220px,0.8fr)_minmax(0,2fr)] xl:items-start">
    <div><h2 id="author-readiness-heading" className="font-semibold">{copy.readiness}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{copy.readinessHint}</p></div>
    <dl className="grid gap-3 text-sm sm:grid-cols-3">
      <div className="min-w-0 rounded-xl bg-muted/30 p-3"><dt className="text-xs font-medium text-muted-foreground">{copy.outline}</dt><dd className="mt-2 font-semibold">{unavailable ? copy.unavailable : `${copy.modules}: ${moduleCount} · ${copy.lessons}: ${lessonCount}`}</dd>
        <dd className="mt-1 text-xs leading-5 text-muted-foreground">{copy.outlineHint}</dd></div>
      <div className="min-w-0 rounded-xl bg-muted/30 p-3"><dt className="text-xs font-medium text-muted-foreground">{copy.changes}</dt><dd className={`mt-2 font-medium ${dirty ? 'text-warning' : 'text-foreground'}`}>{dirty ? copy.unsaved : copy.saved}</dd></div>
      <div className="min-w-0 rounded-xl bg-muted/30 p-3"><dt className="text-xs font-medium text-muted-foreground">{copy.review}</dt><dd className="mt-2 font-medium">{review}</dd></div>
    </dl>
    <p className="border-t border-border pt-3 text-xs leading-5 text-muted-foreground xl:col-span-2">{copy.approvalHint}</p>
  </WorkspacePanel>;
}
