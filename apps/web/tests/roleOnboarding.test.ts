import { describe, expect, it } from 'vitest';
import { getOnboardingHref, getVisibleOnboardingSteps, needsTrialSupport } from '@/components/onboarding/onboardingModel';

const steps = [
  { id: 'team', href: '/admin/team', owner: 'admin' as const },
  { id: 'staff_import', href: '/staff?tab=import', owner: 'methodologist' as const },
  { id: 'documents', href: '/documents', owner: 'methodologist' as const },
  { id: 'first_course', href: '/ai/generate', owner: 'methodologist' as const },
  { id: 'first_assignment', href: '/courses', owner: 'methodologist' as const },
  { id: 'training_log', href: '/training-log', owner: 'methodologist' as const },
];

describe('role-specific onboarding', () => {
  it('keeps governance steps on the admin surface', () => {
    expect(getVisibleOnboardingSteps(steps, 'admin').map((step) => step.id)).toEqual(['team']);
    expect(getOnboardingHref(steps[0], 'admin')).toBe('/admin/team');
  });

  it('keeps learning setup steps on the methodologist surface', () => {
    expect(getVisibleOnboardingSteps(steps, 'methodologist').map((step) => step.id)).toEqual([
      'staff_import', 'documents', 'first_course', 'first_assignment', 'training_log',
    ]);
    expect(getOnboardingHref(steps[4], 'methodologist')).toBe('/courses');
    expect(getOnboardingHref(steps[5], 'methodologist')).toBe('/training-log');
    expect(steps.some((step) => ['/assignments', '/invitations'].includes(step.href))).toBe(false);
  });

  it('does not expose tenant onboarding to a superadmin without tenant context', () => {
    expect(getVisibleOnboardingSteps(steps, 'superadmin')).toEqual([]);
  });
});

describe('trial exhaustion state', () => {
  it('requires support instead of presenting a dead activation action', () => {
    expect(needsTrialSupport('support_required')).toBe(true);
    expect(needsTrialSupport('limited')).toBe(false);
  });
});
