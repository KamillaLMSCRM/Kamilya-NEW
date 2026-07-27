'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Check, Circle, ChevronRight } from 'lucide-react';
import { isAdminOnboardingActionable } from '@/lib/adminOnboarding';
import { TrialStatusPanel, type TrialLimitSnapshot, type TrialState, type TrialAccessState } from '@/components/onboarding/TrialStatusPanel';
import { getOnboardingHref, getVisibleOnboardingSteps } from '@/components/onboarding/onboardingModel';

interface OnboardingStep {
  id: string;
  label: string;
  done: boolean;
  href: string;
  badge: string | null;
  owner?: 'admin' | 'methodologist';
}

interface OnboardingStatus {
  steps: OnboardingStep[];
  completed: boolean;
  trial_ends_at: string | null;
  trial_days_remaining: number | null;
  plan: string | null;
  max_users: number | null;
  active_users: number;
  role: 'admin' | 'methodologist' | 'superadmin' | null;
  trial_state: TrialState;
  trial_access_state: TrialAccessState;
  trial_exhausted_limits: string[];
  trial_usage: Record<string, TrialLimitSnapshot>;
}

/**
 * Role-specific onboarding based on real tenant state.
 *
 * Reads /v1/admin/onboarding-status and renders role-owned steps derived from
 * real DB state. Hidden once everything is done (admin shouldn't see
 * it forever — only when it adds value).
 */
export function OnboardingChecklist() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const role = useAuthStore((s) => s.user?.role);
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/v1/admin/onboarding-status`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          setLoading(false);
          return;
        }
        const data = await res.json();
        if (!cancelled) setStatus(data);
      } catch {
        // Network error — silently fail, don't block the dashboard.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, API_URL]);

  if (loading || !status) {
    return null; // Don't render anything until we know
  }

  const visibleSteps = getVisibleOnboardingSteps(status.steps, role);
  if (visibleSteps.length === 0) return null;
  const visibleCompleted = visibleSteps.every((step) => step.done);
  const doneCount = visibleSteps.filter((s) => s.done).length;
  const totalCount = visibleSteps.length;
  const percent = Math.round((doneCount / totalCount) * 100);

  return (
    <div className="space-y-4">
      <TrialStatusPanel
        state={status.trial_state || 'not_trial'}
        accessState={status.trial_access_state || 'not_applicable'}
        daysRemaining={status.trial_days_remaining}
        exhaustedLimits={status.trial_exhausted_limits || []}
        usage={status.trial_usage || {}}
      />
      {visibleCompleted ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Check className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <div className="font-medium text-foreground">{t('onboarding.allSetTitle')}</div>
              <div className="text-sm text-muted-foreground">{t('onboarding.allSetSubtitle')}</div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>
            {role === 'admin' ? t('onboarding.adminTitle') : t('onboarding.methodologistTitle')}
          </CardTitle>
          <Badge variant="outline">
            {t('onboarding.progress', { done: doneCount, total: totalCount })}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {role === 'admin' ? t('onboarding.adminSubtitle') : t('onboarding.methodologistSubtitle')}
        </p>
      </CardHeader>
      <CardContent className="space-y-1">
        {/* Progress bar */}
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-primary transition-all"
            style={{ width: `${percent}%` }}
            aria-label={`${percent}%`}
          />
        </div>

        {/* Steps */}
        <ul className="mt-3 space-y-1" role="list">
          {visibleSteps.map((step) => (
            <li key={step.id}>
              {role === 'admin' && isAdminOnboardingActionable({ href: getOnboardingHref(step, role) }) ? (
                <Link
                  href={getOnboardingHref(step, role)}
                  className="group flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-muted transition-colors"
                  aria-current={step.done ? 'false' : 'step'}
                >
                  <StepContent step={step} />
                </Link>
              ) : role === 'methodologist' ? (
                <Link
                  href={getOnboardingHref(step, role)}
                  className="group flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-muted transition-colors"
                  aria-current={step.done ? 'false' : 'step'}
                >
                  <StepContent step={step} />
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      </CardContent>
        </Card>
      )}
    </div>
  );
}

function StepContent({ step }: { step: OnboardingStep }) {
  return (
    <>
                <span
                  className={
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ' +
                    (step.done
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border text-muted-foreground')
                  }
                  aria-hidden="true"
                >
                  {step.done ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <Circle className="h-3.5 w-3.5" />
                  )}
                </span>
                <span
                  className={
                    'flex-1 ' +
                    (step.done
                      ? 'text-muted-foreground line-through'
                      : 'text-foreground font-medium')
                  }
                >
                  {step.label}
                </span>
                {step.badge && (
                  <Badge variant="secondary" className="ml-auto">
                    {step.badge}
                  </Badge>
                )}
                {!step.done && (
                  <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                )}
    </>
  );
}
