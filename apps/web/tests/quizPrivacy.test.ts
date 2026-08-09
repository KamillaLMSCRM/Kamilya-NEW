import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const quizPlayerSource = readFileSync(
  resolve(process.cwd(), 'src/app/courses/quiz/[quizId]/page.tsx'),
  'utf8',
);

describe('learner quiz privacy', () => {
  it('shows an aggregate result without an answer-review mode', () => {
    expect(quizPlayerSource).not.toContain('correct_choice_ids');
    expect(quizPlayerSource).not.toContain('showReview');
    expect(quizPlayerSource).not.toContain('quiz.review');
    expect(quizPlayerSource).not.toContain('q.explanation');
  });
});
