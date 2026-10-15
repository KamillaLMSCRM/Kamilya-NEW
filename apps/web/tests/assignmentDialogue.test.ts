import { describe, expect, it } from 'vitest';

import {
  appendAssignmentInstruction,
  isAssignmentDialogueHistory,
} from '@/lib/assignmentDialogue';

describe('assignment dialogue history', () => {
  it('appends an instruction without mutating history or rewriting text', () => {
    const history = ['  Assign the course to A-12.  '];
    const instruction = '\tSet the deadline to 2026-11-01.\n';

    const result = appendAssignmentInstruction(history, instruction);

    expect(result).toEqual([...history, instruction]);
    expect(result).not.toBe(history);
    expect(history).toEqual(['  Assign the course to A-12.  ']);
  });

  it('accepts the exact per-turn and total history boundaries', () => {
    const twoThousand = 'x'.repeat(2000);
    const oneThousand = 'y'.repeat(1000);
    const history = [twoThousand, twoThousand, oneThousand];

    expect(isAssignmentDialogueHistory(history)).toBe(true);
    expect(appendAssignmentInstruction(history, oneThousand)).toEqual([
      ...history,
      oneThousand,
    ]);
  });

  it('rejects a blank instruction and leaves the input unchanged', () => {
    const history = ['Keep this text'];

    expect(() => appendAssignmentInstruction(history, ' \t\n ')).toThrow(
      RangeError,
    );
    expect(history).toEqual(['Keep this text']);
  });

  it('rejects an instruction longer than 2000 characters', () => {
    expect(() => appendAssignmentInstruction([], 'x'.repeat(2001))).toThrow(
      RangeError,
    );
  });

  it('rejects a nonstring instruction at the runtime boundary', () => {
    expect(() =>
      appendAssignmentInstruction([], 42 as unknown as string),
    ).toThrow(RangeError);
  });

  it('rejects more than four stored turns', () => {
    const history = ['1', '2', '3', '4'];

    expect(() => appendAssignmentInstruction(history, '5')).toThrow(RangeError);
    expect(history).toEqual(['1', '2', '3', '4']);
  });

  it('rejects more than 6000 total stored characters', () => {
    const history = ['x'.repeat(2000), 'y'.repeat(2000), 'z'.repeat(1999)];

    expect(() => appendAssignmentInstruction(history, 'w'.repeat(2))).toThrow(
      RangeError,
    );
    expect(isAssignmentDialogueHistory(history)).toBe(true);
  });

  it('validates empty history and rejects invalid history values', () => {
    expect(isAssignmentDialogueHistory([])).toBe(true);
    expect(isAssignmentDialogueHistory(['ok', ' '.repeat(1)])).toBe(false);
    expect(isAssignmentDialogueHistory(['x'.repeat(2001)])).toBe(false);
    expect(isAssignmentDialogueHistory(['x'.repeat(2000), 'y'.repeat(2000), 'z'.repeat(2001)])).toBe(false);
    expect(isAssignmentDialogueHistory(['1', '2', '3', '4', '5'])).toBe(false);
    expect(isAssignmentDialogueHistory(['x'.repeat(6001)])).toBe(false);
    expect(isAssignmentDialogueHistory(['ok', 42] as unknown)).toBe(false);
    expect(isAssignmentDialogueHistory(null)).toBe(false);
  });

  it('rejects invalid existing history before appending', () => {
    expect(() =>
      appendAssignmentInstruction(['ok', ' '.repeat(1)], 'next'),
    ).toThrow(RangeError);
    expect(() =>
      appendAssignmentInstruction(['x'.repeat(2001)], 'next'),
    ).toThrow(RangeError);
  });
});
