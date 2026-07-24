import { describe, expect, it } from 'vitest';

import { cohortUserOptions } from '../src/app/cohorts/user-list-contract';

describe('cohort user list contract', () => {
  it('reads users from UserListResponse and builds display names', () => {
    const result = cohortUserOptions({
      users: [
        { id: 'u1', first_name: 'Айжан', last_name: 'Серикова', email: 'a@example.kz' },
        { id: 'u2', first_name: null, last_name: null, email: 'b@example.kz' },
      ],
      total: 2,
      page: 1,
      per_page: 500,
    });

    expect(result).toEqual([
      { id: 'u1', name: 'Айжан Серикова' },
      { id: 'u2', name: 'b@example.kz' },
    ]);
  });

  it('returns an empty list only when the successful response has no users', () => {
    expect(cohortUserOptions({ users: [], total: 0, page: 1, per_page: 500 })).toEqual([]);
  });
});
