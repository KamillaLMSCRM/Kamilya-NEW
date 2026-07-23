import { canAccessRoute } from '@/lib/rolePolicy';

export interface AdminOnboardingStep {
  href: string;
}

/**
 * Admin onboarding may report tenant-wide learning progress, but an admin must
 * never receive an actionable link to methodologist-owned work (ADR-0012).
 */
export function isAdminOnboardingActionable(step: AdminOnboardingStep): boolean {
  return canAccessRoute('admin', step.href);
}
