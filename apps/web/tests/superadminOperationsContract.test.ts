import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessRegisteredRoute, getNavigationRoutes } from '@/lib/routeRegistry';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/super/operations/page.tsx'), 'utf8');
const locales = ['en', 'ru', 'kk'].map((locale) => JSON.parse(readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8')));

describe('superadmin operations UI contract', () => {
  it('exposes the operations route only to superadmin', () => {
    expect(getNavigationRoutes('superadmin', 'sidebar').some((route) => route.href === '/admin/super/operations')).toBe(true);
    for (const role of ['admin', 'methodologist', 'student'] as const) {
      expect(getNavigationRoutes(role, 'sidebar').some((route) => route.href === '/admin/super/operations')).toBe(false);
      expect(canAccessRegisteredRoute(role, '/admin/super/operations')).toBe(false);
    }
    expect(canAccessRegisteredRoute('superadmin', '/admin/super/operations')).toBe(true);
  });

  it('keeps preview, confirmation, stale refresh and aggregate-only contracts in the UI', () => {
    expect(page).toContain('/admin/super/operations/summary');
    expect(page).toContain('/admin/super/operations/cleanup-synthetic');
    expect(page).toContain('/admin/super/operations/recover-stale-ai-jobs');
    expect(page).toContain('dry_run: true');
    expect(page).toContain("CLEANUP_SYNTHETIC_TENANTS");
    expect(page).toContain("RECOVER_STALE_AI_JOBS");
    expect(page).toContain('confirm_token');
    expect(page).toContain('staleRecovery');
    expect(page).toContain("terminal_status: 'cancelled'");
    expect(page).toContain('setStale');
    expect(page).toContain('await loadAll(true)');
    expect(page).not.toMatch(/resend/i);
  });

  it('renders bounded runtime and worker metrics with an unavailable state', () => {
    expect(page).toContain('rss_memory_bytes');
    expect(page).toContain('filesystem.used_percent');
    expect(page).toContain('registered_required_tasks');
    expect(page).toContain('superadmin.operations.unavailable');
    expect(page).toContain('TaskList');
  });

  it('keeps runtime metric translations present in every supported locale', () => {
    for (const locale of locales) {
      const operations = locale.superadmin.operations;
      expect(operations.unavailable).toBeTruthy();
      expect(operations.host.title).toBeTruthy();
      expect(operations.cpu).toBeTruthy();
      expect(operations.rss).toBeTruthy();
      expect(operations.filesystem.used).toBeTruthy();
      expect(operations.celery.registered).toBeTruthy();
      expect(operations.celery.missing).toBeTruthy();
      expect(operations.staleRecovery.title).toBeTruthy();
      expect(operations.staleRecovery.confirm).toBeTruthy();
      expect(operations.staleRecovery.description.length).toBeGreaterThan(10);
    }
  });
});
