import { describe, expect, it } from 'vitest';
import { isAdminOnboardingActionable } from '@/lib/adminOnboarding';

describe('admin onboarding CTA ownership', () => {
  it.each([
    ['/admin/team', true],
    ['/admin/kiosks', true],
    ['/settings', true],
    ['/staff?tab=import', false],
    ['/documents', false],
    ['/ai/generate', false],
    ['/assignments', false],
  ])('treats %s as actionable for admin: %s', (href, expected) => {
    expect(isAdminOnboardingActionable({ href })).toBe(expected);
  });
});
