export type OnboardingRole = 'admin' | 'methodologist' | 'superadmin';
export type OnboardingOwner = 'admin' | 'methodologist';

export interface OwnedOnboardingStep {
  id: string;
  owner?: OnboardingOwner;
  href: string;
}

const FALLBACK_OWNER: Record<string, OnboardingOwner> = {
  team: 'admin',
};

export function getVisibleOnboardingSteps<T extends OwnedOnboardingStep>(
  steps: T[],
  role: string | null | undefined,
): T[] {
  if (role !== 'admin' && role !== 'methodologist') return [];
  return steps.filter((step) => {
    const owner = step.owner || FALLBACK_OWNER[step.id] || 'methodologist';
    return owner === role;
  });
}

export function getOnboardingHref(step: OwnedOnboardingStep, _role: string | null | undefined): string {
  return step.href;
}

export function needsTrialSupport(
  accessState: 'available' | 'limited' | 'support_required' | 'not_applicable',
): boolean {
  return accessState === 'support_required';
}
