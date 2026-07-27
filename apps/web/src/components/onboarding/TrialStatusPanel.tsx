'use client';

import { AlertTriangle, CheckCircle2, LifeBuoy } from 'lucide-react';
import { Badge, Card, CardContent } from '@/components/ui';
import { useT } from '@/i18n/useT';

export type TrialState = 'active' | 'nearing_expiry' | 'expired' | 'not_trial';
export type TrialAccessState = 'available' | 'limited' | 'support_required' | 'not_applicable';

export interface TrialLimitSnapshot {
  used: number;
  limit: number | null;
  remaining: number | null;
}

interface TrialStatusPanelProps {
  state: TrialState;
  accessState: TrialAccessState;
  daysRemaining: number | null;
  exhaustedLimits: string[];
  usage: Record<string, TrialLimitSnapshot>;
}

const SUPPORT_HREF = 'mailto:support@kml.kz?subject=Kamilya%20LMS%20trial';

const STATE_LABEL_KEYS = {
  active: 'trialStatus.active',
  nearing_expiry: 'trialStatus.nearingExpiry',
  expired: 'trialStatus.expired',
} as const;

const LIMIT_LABELS = {
  ai_courses: 'admin.trial.aiCourse',
  jd_courses: 'admin.trial.jdCourse',
  learners: 'admin.trial.learners',
  system_users: 'admin.trial.systemUsers',
} as const;

export function TrialStatusPanel({
  state,
  accessState,
  daysRemaining,
  exhaustedLimits,
  usage,
}: TrialStatusPanelProps) {
  const { t } = useT();
  if (state === 'not_trial') return null;

  const isSupportRequired = accessState === 'support_required';
  const isNearing = state === 'nearing_expiry';
  const hasExhaustedLimits = exhaustedLimits.length > 0;
  const showSupportContact = isSupportRequired || isNearing || exhaustedLimits.length > 0;
  const exhaustedNames = exhaustedLimits
    .map((resource) => {
      const labelKey = LIMIT_LABELS[resource as keyof typeof LIMIT_LABELS];
      return labelKey ? t(labelKey) : resource;
    })
    .join(', ');

  return (
    <Card className={isSupportRequired ? 'border-destructive/40' : isNearing || hasExhaustedLimits ? 'border-warning/40' : ''}>
      <CardContent className="p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 gap-3">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${isSupportRequired ? 'bg-destructive/10 text-destructive' : isNearing ? 'bg-warning/10 text-warning' : 'bg-success/10 text-success'}`}>
              {isSupportRequired ? <AlertTriangle className="h-5 w-5" aria-hidden="true" /> : isNearing ? <LifeBuoy className="h-5 w-5" aria-hidden="true" /> : <CheckCircle2 className="h-5 w-5" aria-hidden="true" />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-foreground">{t('admin.trial.title')}</h2>
                <Badge variant={isSupportRequired ? 'destructive' : isNearing ? 'outline' : 'secondary'}>
                  {t(STATE_LABEL_KEYS[state])}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {isSupportRequired
                  ? t('trialStatus.expiredHint')
                  : isNearing
                    ? t('trialStatus.nearingHint')
                    : t('onboarding.trialDays', { days: daysRemaining ?? 0 })}
              </p>
            </div>
          </div>
          {showSupportContact && (
            <a
              href={SUPPORT_HREF}
              className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-lg border border-destructive/30 px-3 text-sm font-medium text-destructive hover:bg-destructive/5"
            >
              {t('trialStatus.contact')}
            </a>
          )}
        </div>

        {exhaustedLimits.length > 0 && (
          <div className="mt-4 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground" role="status">
            {t('trialStatus.exhaustedPrefix')}<strong>{exhaustedNames}</strong>{t('trialStatus.exhaustedSuffix')}
          </div>
        )}

        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {Object.entries(usage).map(([resource, item]) => {
            const labelKey = LIMIT_LABELS[resource as keyof typeof LIMIT_LABELS];
            if (!labelKey) return null;
            const exhausted = item.limit != null && item.remaining === 0;
            return (
              <div key={resource} className={`rounded-lg border px-3 py-2 text-sm ${exhausted ? 'border-warning/30 bg-warning/10' : 'border-border bg-muted/20'}`}>
                <div className="truncate text-xs text-muted-foreground">{t(labelKey)}</div>
                <div className="mt-1 font-medium text-foreground">
                  {item.limit == null ? `${item.used} / ${t('admin.trial.unlimited')}` : `${item.used} / ${item.limit}`}
                </div>
                {item.remaining != null && <div className="text-xs text-muted-foreground">{t('admin.trial.remaining')}: {item.remaining}</div>}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
