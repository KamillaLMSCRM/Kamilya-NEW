export const TEAM_ROLES = ['methodologist', 'admin'] as const;

export type TeamRole = (typeof TEAM_ROLES)[number];

export interface TeamMemberForm {
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  password: string;
}

interface ExistingTeamAccount {
  id: string;
}

export interface TeamMemberSubmission {
  path: string;
  body: Record<string, string>;
}

export function getAssignableTeamRoles(assignedRoles: string[] = []): TeamRole[] {
  return TEAM_ROLES.filter((role) => !assignedRoles.includes(role));
}

export function buildTeamMemberSubmission(
  form: TeamMemberForm,
  existingAccount: ExistingTeamAccount | null,
): TeamMemberSubmission {
  if (existingAccount) {
    return {
      path: `/v1/users/${existingAccount.id}/roles`,
      body: { role: form.role },
    };
  }

  const body: Record<string, string> = {
    email: form.email.trim().toLowerCase(),
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim(),
    role: form.role,
  };
  if (form.password) body.password = form.password;

  return {
    path: '/v1/users',
    body,
  };
}
