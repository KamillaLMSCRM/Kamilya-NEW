'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { Check, Circle, ChevronRight } from 'lucide-react';

interface OnboardingStep {
  id: string;
  label: string;
  done: boolean;
  href: string;
  badge: string | null;
}

interface OnboardingStatus {
  steps: OnboardingStep[];
  completed: boolean;
  trial_ends_at: string | null;
  trial_days_remaining: number | null;
  plan: string | null;
  max_users: number | null;
  active_users: number;
}

/**
 * OnboardingChecklist — P0.6 first-tenant hardening.
 *
 * Reads /v1/admin/onboarding-status and renders 7 steps derived from
 * real DB state. Hidden once everything is done (admin shouldn't see
 * it forever — only when it adds value).
 */
export function OnboardingChecklist() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
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

  // If all steps done, show a small "you're all set" panel.
  if (status.completed) {
    return (
      <Card>
        <CardContent className="p-4 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Check className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <div className="font-medium text-foreground">
              {t('onboarding.allSetTitle')}
            </div>
            <div className="text-sm text-muted-foreground">
              {t('onboarding.allSetSubtitle')}
            </div>
          </div>
          {status.trial_days_remaining != null && status.trial_days_remaining > 0 && (
            <Badge variant="secondary">
              {t('onboarding.trialDays', { days: status.trial_days_remaining })}
            </Badge>
          )}
        </CardContent>
      </Card>
    );
  }

  const doneCount = status.steps.filter((s) => s.done).length;
  const totalCount = status.steps.length;
  const percent = Math.round((doneCount / totalCount) * 100);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{t('onboarding.title')}</CardTitle>
          <Badge variant="outline">
            {t('onboarding.progress', { done: doneCount, total: totalCount })}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('onboarding.subtitle')}
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

        {/* Trial info */}
        {status.trial_days_remaining != null && status.trial_days_remaining > 0 && (
          <div className="mt-3 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
            <span className="text-muted-foreground">{t('onboarding.trial')}</span>{' '}
            <span className="font-medium text-foreground">
              {t('onboarding.trialDays', { days: status.trial_days_remaining })}
            </span>
            {status.max_users != null && (
              <>
                {' · '}
                <span className="text-muted-foreground">{t('onboarding.users')}</span>{' '}
                <span className="font-medium text-foreground">
                  {status.active_users} / {status.max_users}
                </span>
              </>
            )}
          </div>
        )}

        {/* Steps */}
        <ul className="mt-3 space-y-1" role="list">
          {status.steps.map((step) => (
            <li key={step.id}>
              <Link
                href={step.href}
                className="group flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-muted transition-colors"
                aria-current={step.done ? 'false' : 'step'}
              >
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
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}