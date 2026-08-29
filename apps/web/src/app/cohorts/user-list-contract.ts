export type CohortUser = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  role?: string | null;
  is_active?: boolean;
};

export type UserListResponse = {
  users: CohortUser[];
  total: number;
  page: number;
  per_page: number;
};

export type CohortUserOption = {
  id: string;
  name: string;
};

export const COHORT_MANAGER_ROLE = 'methodologist' as const;

export function cohortMemberPayload(userIds: string[]) {
  return { user_ids: [...new Set(userIds)] };
}

export function cohortUserOptions(response: UserListResponse): CohortUserOption[] {
  return response.users
    .filter((user) => user.role === 'student' && user.is_active !== false)
    .map((user) => ({
      id: user.id,
      name:
        `${user.first_name ?? ''} ${user.last_name ?? ''}`.trim() ||
        user.email ||
        user.id,
    }));
}
