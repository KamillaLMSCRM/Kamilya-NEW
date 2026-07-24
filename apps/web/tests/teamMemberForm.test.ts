import { describe, expect, it } from 'vitest';

import {
  buildTeamMemberSubmission,
  getAssignableTeamRoles,
} from '@/lib/teamMemberForm';

const form = {
  email: ' Existing@Example.com ',
  first_name: ' Existing ',
  last_name: ' User ',
  role: 'methodologist',
  password: '',
};

describe('team member submission', () => {
  it('adds a role to an existing account without posting hidden profile fields', () => {
    expect(buildTeamMemberSubmission(form, { id: 'user-123' })).toEqual({
      path: '/v1/users/user-123/roles',
      body: { role: 'methodologist' },
    });
  });

  it('creates a new account with normalized fields', () => {
    expect(buildTeamMemberSubmission({ ...form, password: 'password123' }, null)).toEqual({
      path: '/v1/users',
      body: {
        email: 'existing@example.com',
        first_name: 'Existing',
        last_name: 'User',
        role: 'methodologist',
        password: 'password123',
      },
    });
  });

  it('does not offer a role that the account already has', () => {
    expect(getAssignableTeamRoles(['admin', 'methodologist'])).toEqual(['org_admin']);
  });
});
