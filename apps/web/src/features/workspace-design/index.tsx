import type { HTMLAttributes, ReactNode } from 'react';
import { Logo } from '@/components/brand/Logo';
import { cn } from '@/lib/utils';

export interface WorkspaceHeadingProps {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function WorkspacePageHeader({ title, description, eyebrow, icon, actions, className }: WorkspaceHeadingProps) {
  return <header data-workspace-header className={cn('flex min-w-0 flex-col gap-5 lg:flex-row lg:items-start lg:justify-between', className)}>
    <div className="flex min-w-0 items-start gap-3.5">
      {icon && <span aria-hidden="true" className="mt-0.5 hidden h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary/15 bg-primary/5 text-primary sm:flex [&>svg]:h-5 [&>svg]:w-5">{icon}</span>}
      <div className="min-w-0">
        {eyebrow && <p className="mb-2 text-xs font-semibold leading-5 text-primary">{eyebrow}</p>}
        <h1 className="break-words text-[28px] font-semibold leading-tight tracking-tight text-foreground sm:text-3xl">{title}</h1>
        {description && <div className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</div>}
      </div>
    </div>
    {actions && <div data-workspace-actions className="flex min-w-0 flex-wrap items-center gap-2 lg:shrink-0 lg:justify-end">{actions}</div>}
  </header>;
}

export interface WorkspacePageProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'>, Partial<Omit<WorkspaceHeadingProps, 'className'>> {
  id: string;
  children: ReactNode;
}

export function WorkspacePage({ id, title, description, eyebrow, icon, actions, children, className, ...props }: WorkspacePageProps) {
  return <div {...props} id={id} data-redesign-page={id} className={cn('min-w-0 space-y-6', className)}>
    {title != null && <WorkspacePageHeader title={title} description={description} eyebrow={eyebrow} icon={icon} actions={actions} />}
    {children}
  </div>;
}

export interface WorkspacePanelProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  bodyClassName?: string;
  padded?: boolean;
}

export function WorkspacePanel({ title, description, actions, children, className, bodyClassName, padded = true, ...props }: WorkspacePanelProps) {
  return <section {...props} data-workspace-panel className={cn('min-w-0 rounded-2xl border border-border bg-card text-card-foreground shadow-sm', className)}>
    {(title || description || actions) && <div className="flex min-w-0 flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
      <div className="min-w-0">{title && <h2 className="break-words text-lg font-semibold leading-6 text-foreground">{title}</h2>}{description && <div className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</div>}</div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>}
    <div className={cn('min-w-0', padded && 'p-5 sm:p-6', bodyClassName)}>{children}</div>
  </section>;
}

export function WorkspaceToolbar({ children, className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} data-workspace-toolbar className={cn('flex min-w-0 flex-wrap items-end gap-3 rounded-2xl border border-border bg-card p-4', className)}>{children}</div>;
}

export function WorkspaceEmpty({ title, description, icon, action, className }: {
  title: ReactNode; description?: ReactNode; icon?: ReactNode; action?: ReactNode; className?: string;
}) {
  return <div data-workspace-empty className={cn('min-w-0 rounded-2xl border border-dashed border-border bg-card px-5 py-12 text-center', className)}>
    {icon && <div aria-hidden="true" className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-muted/50 text-muted-foreground [&>svg]:h-6 [&>svg]:w-6">{icon}</div>}
    <h2 className="text-base font-semibold leading-6 text-foreground">{title}</h2>
    {description && <div className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">{description}</div>}
    {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
  </div>;
}

export function WorkspaceStat({ label, value, hint, icon, tone = 'default', className }: {
  label: ReactNode; value?: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: 'default' | 'warning' | 'success'; className?: string;
}) {
  return <div data-workspace-stat className={cn('min-w-0 rounded-2xl border border-border bg-card p-4 sm:p-5', className)}>
    <div className="flex items-start justify-between gap-3"><p className="text-xs font-medium leading-5 text-muted-foreground">{label}</p>{icon && <span aria-hidden="true" className="shrink-0 text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}</div>
    <p className={cn('mt-2 break-words text-3xl font-semibold leading-tight tabular-nums tracking-tight', tone === 'warning' ? 'text-warning' : tone === 'success' ? 'text-success' : 'text-foreground')}>{value ?? '—'}</p>
    {hint && <div className="mt-2 text-xs leading-5 text-muted-foreground">{hint}</div>}
  </div>;
}

export function PublicWorkspace({ id, title, description, eyebrow, icon, actions, children, className, as: Element = 'main', logoHref }: {
  id: string; title?: ReactNode; description?: ReactNode; eyebrow?: ReactNode; icon?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; as?: 'main' | 'div'; logoHref?: string;
}) {
  return <Element id={Element === 'main' ? 'main-content' : undefined} data-redesign-page={id} data-public-workspace className={cn('min-h-dvh min-w-0 bg-background px-4 py-8 text-foreground sm:px-6 sm:py-12', className)}>
    <div className="mx-auto w-full min-w-0 max-w-5xl space-y-8">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-4">
        {logoHref ? <a href={logoHref} className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><Logo size={32} withSubtitle={false} /></a> : <Logo size={32} withSubtitle={false} />}
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {title != null && <WorkspacePageHeader title={title} description={description} eyebrow={eyebrow} icon={icon} />}
      {children}
    </div>
  </Element>;
}
