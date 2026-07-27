import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { canAccessRegisteredRoute, getNavigationRoutes } from '@/lib/routeRegistry';

const page = readFileSync(resolve(process.cwd(), 'src/app/admin/super/operations/page.tsx'), 'utf8');

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
    expect(page).toContain('dry_run: true');
    expect(page).toContain("CLEANUP_SYNTHETIC_TENANTS");
    expect(page).toContain('confirm_token');
    expect(page).toContain('setStale');
    expect(page).toContain('await loadAll(true)');
    expect(page).not.toMatch(/resend/i);
  });
});
