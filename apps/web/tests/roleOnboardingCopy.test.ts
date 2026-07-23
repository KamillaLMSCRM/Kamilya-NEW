import { describe, expect, it } from 'vitest';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import { DEMO_ADMIN_COPY } from '@/lib/demoRoleCopy';
import { interpolate } from '@/i18n/useT';

describe('role onboarding copy', () => {
  it('describes the demo administrator without methodologist-owned course work', () => {
    expect(DEMO_ADMIN_COPY.description).not.toContain('курс');
    expect(DEMO_ADMIN_COPY.redirect).toBe('/admin');
  });

  it.each([['RU', ru], ['KK', kk]] as const)('provides complete Telegram and password guidance in %s', (_, locale) => {
    expect(locale.auth.passwordMinHint).not.toMatch(/Minimum 8 characters/i);
    expect(locale.auth.telegramPrerequisite).toBeTruthy();
    expect(locale.auth.telegramInstructions).toBeTruthy();
    expect(locale.auth.telegramRecovery).toBeTruthy();
  });

  it.each([['RU', ru], ['KK', kk]] as const)('renders onboarding progress without braces in %s', (_, locale) => {
    expect(interpolate(locale.onboarding.progress, { done: 6, total: 7 })).not.toContain('{');
    expect(interpolate(locale.onboarding.trialDays, { days: 14 })).not.toContain('{');
  });
});
