import { describe, expect, it } from 'vitest';

import { getAssignmentSourceInfo } from '@/lib/assignmentSource';

describe('assignment source presentation', () => {
  it('allows direct assignments to be removed locally', () => {
    const info = getAssignmentSourceInfo('manual');
    expect(info.labelKey).toBe('assignmentSources.manual.label');
    expect(info.managedByRule).toBe(false);
  });

  it.each(['position', 'department', 'cohort', 'learning_path'])(
    'explains rule-managed source %s',
    (source) => {
      const info = getAssignmentSourceInfo(source);
      expect(info.descriptionKey).toMatch(/^assignmentSources\./);
      expect(info.managedByRule).toBe(true);
    },
  );

  it('fails closed for an unknown automatic source', () => {
    expect(getAssignmentSourceInfo('future_rule').managedByRule).toBe(true);
  });
});
