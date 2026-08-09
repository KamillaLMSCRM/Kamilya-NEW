import { describe, expect, it } from 'vitest';

import {
  adaptationResumeStep,
  adaptationSteps,
  completedAnswerCount,
  firstIncompleteStep,
  firstMissingAnswer,
} from '@/lib/blueprintAdaptation';

const checklist = adaptationSteps.flatMap((step) => step.itemIds.map((id) => ({ id, required: true })));

describe('finance blueprint adaptation flow', () => {
  it('groups all eight required decisions into three short steps', () => {
    expect(adaptationSteps.map((step) => step.itemIds.length)).toEqual([3, 3, 2]);
    expect(new Set(checklist.map((item) => item.id)).size).toBe(8);
  });

  it('treats whitespace as missing and returns the first field to focus', () => {
    const answers = {
      access_and_offboarding: '  ',
      approved_systems: 'Corporate email',
    };

    expect(firstMissingAnswer(adaptationSteps[0], checklist, answers)).toBe('access_and_offboarding');
    expect(firstIncompleteStep(checklist, answers)).toBe(0);
  });

  it('moves to the next incomplete step without losing previous answers', () => {
    const answers = Object.fromEntries(adaptationSteps[0].itemIds.map((id) => [id, `answer:${id}`]));

    expect(firstIncompleteStep(checklist, answers)).toBe(1);
    expect(completedAnswerCount(checklist, answers)).toBe(3);
    expect(adaptationResumeStep(checklist, answers)).toBe(1);
  });

  it('is complete only when all eight required answers contain text', () => {
    const answers = Object.fromEntries(checklist.map((item) => [item.id, 'Не применяется: исключений нет']));

    expect(firstIncompleteStep(checklist, answers)).toBe(-1);
    expect(completedAnswerCount(checklist, answers)).toBe(8);
    expect(adaptationResumeStep(checklist, answers)).toBe(2);
  });

  it('does not count optional fields as required progress', () => {
    expect(completedAnswerCount(
      [...checklist, { id: 'optional_document', required: false }],
      { optional_document: 'selected' },
    )).toBe(0);
    expect(firstMissingAnswer(
      { ...adaptationSteps[0], itemIds: ['optional_document'] },
      [{ id: 'optional_document', required: false }],
      {},
    )).toBeUndefined();
  });
});
