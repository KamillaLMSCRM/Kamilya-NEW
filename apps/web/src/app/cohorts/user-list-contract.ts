export type CohortUser = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
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

export function cohortUserOptions(response: UserListResponse): CohortUserOption[] {
  return response.users.map((user) => ({
    id: user.id,
    name:
      `${user.first_name ?? ''} ${user.last_name ?? ''}`.trim() ||
      user.email ||
      user.id,
  }));
}
