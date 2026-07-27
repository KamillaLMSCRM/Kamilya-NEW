import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { cohortMemberPayload, COHORT_MANAGER_ROLE } from '../src/app/cohorts/user-list-contract';

describe('cohort audience contract', () => {
  it('allows only the methodologist to manage the audience', () => {
    expect(COHORT_MANAGER_ROLE).toBe('methodologist');
  });

  it('deduplicates member ids without introducing course links', () => {
    expect(cohortMemberPayload(['u1', 'u1', 'u2'])).toEqual({ user_ids: ['u1', 'u2'] });
  });

  it('does not expose course or assignment controls in the cohort page', () => {
    const source = readFileSync(resolve(__dirname, '../src/app/cohorts/page.tsx'), 'utf8');
    expect(source).not.toContain("'/v1/courses'");
    expect(source).not.toContain('/apply');
    expect(source).not.toContain('/progress');
    expect(source).not.toContain('courseIds');
    expect(source).toContain("role === COHORT_MANAGER_ROLE");
    expect(source).toContain('/members`');
    expect(source).toContain('learningPaths.forbidden');
  });
});
