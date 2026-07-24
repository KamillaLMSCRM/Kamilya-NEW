import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { getNavigationRoutes } from '@/lib/routeRegistry';

const source = readFileSync(resolve(process.cwd(), 'src/app/admin/page.tsx'), 'utf8');

describe('tenant admin dashboard role contract', () => {
  it('does not request or render learning-management dashboard data', () => {
    expect(source).not.toContain('/v1/admin/stats');
    expect(source).not.toContain('OnboardingChecklist');
    expect(source).not.toContain('/staff?tab=');
    expect(source).not.toContain('/courses');
    expect(source).not.toContain('/assignments');
    expect(source).not.toContain('/training-log');
  });

  it('loads only the system-team preview and tenant plan usage', () => {
    expect(source).toContain('/v1/users?per_page=5');
    expect(source).toContain('/v1/admin/trial-usage');
    expect(source).not.toContain('include_students=true');
  });

  it('does not expose the all-user export as a system-team export', () => {
    expect(source).not.toContain('/v1/admin/export/users');
    expect(source).not.toContain('handleExport');
  });

  it('derives administrative quick actions from the shared registry', () => {
    const hrefs = getNavigationRoutes('admin', 'sidebar').map(({ href }) => href);
    expect(hrefs).toEqual([
      '/admin',
      '/admin/team',
      '/admin/kiosks',
      '/settings',
      '/admin/settings/integrations',
      '/admin/certificates/settings',
    ]);
    expect(source).toContain("getNavigationRoutes(role, 'sidebar')");
  });

  it.each(['ru', 'en', 'kk'])('localizes the system-team dashboard in %s', (locale) => {
    const messages = JSON.parse(
      readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8'),
    );
    expect(messages.admin.systemTeam).toBeTruthy();
    expect(messages.admin.quickActions).toBeTruthy();
    expect(messages.admin.viewSystemTeam).toBeTruthy();
  });
});
