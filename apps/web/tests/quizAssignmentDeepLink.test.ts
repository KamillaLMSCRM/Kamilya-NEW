import { describe, expect, it } from 'vitest';

import { firstQuizForAssignments } from '../src/app/quizzes/assignment-deep-link';

describe('quiz assignment deep-link', () => {
  it('selects the first quiz in the grouped course tree', () => {
    const first = { id: 'quiz-1', title: 'Первый тест' };
    const second = { id: 'quiz-2', title: 'Второй тест' };

    expect(firstQuizForAssignments({
      courses: [{
        modules: [{
          lessons: [{ quiz: null }, { quiz: first }, { quiz: second }],
        }],
      }],
      orphans: [],
    })).toBe(first);
  });

  it('falls back to an orphan quiz and preserves an honest empty state', () => {
    const orphan = { id: 'orphan-1' };
    const emptyTree = { courses: [], orphans: [] };

    expect(firstQuizForAssignments({ courses: [], orphans: [{ quiz: orphan }] })).toBe(orphan);
    expect(firstQuizForAssignments(emptyTree)).toBeNull();
  });
});
