import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const profileSource = readFileSync(resolve(process.cwd(), 'src/app/profile/page.tsx'), 'utf8');
const settingsSource = readFileSync(resolve(process.cwd(), 'src/app/settings/page.tsx'), 'utf8');
const topBarSource = readFileSync(resolve(process.cwd(), 'src/components/layout/TopBar.tsx'), 'utf8');

describe('common profile contract', () => {
  it('loads and updates only the authenticated user profile', () => {
    expect(profileSource).toContain("api.get('/v1/users/me')");
    expect(profileSource).toContain("api.patch('/v1/users/me'");
    expect(profileSource).toContain('first_name');
    expect(profileSource).toContain('last_name');
    expect(profileSource).toContain('nav.myProfile');
    expect(profileSource).toContain('readOnly');
  });

  it('keeps personal profile fields out of tenant settings', () => {
    expect(settingsSource).not.toContain('/v1/users/me');
    expect(settingsSource).not.toContain('first_name');
    expect(settingsSource).not.toContain('last_name');
    expect(settingsSource).not.toContain('type="email"');
    expect(settingsSource).toContain('/admin/team');
    expect(settingsSource).toContain('/admin/settings/integrations');
  });

  it('provides a visible profile entry from the top bar', () => {
    expect(topBarSource).toContain('href="/profile"');
    expect(topBarSource).toContain('nav.myProfile');
  });
});
