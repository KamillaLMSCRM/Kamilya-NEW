import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/app/quizzes/page.tsx'), 'utf8');

describe('quiz freshness review', () => {
  it('shows a stale-quiz warning and an explicit methodologist approval action', () => {
    expect(source).toContain("selectedQuiz.review_status === 'needs_review'");
    expect(source).toContain('/approve`');
    expect(source).toContain('Урок изменён после создания теста');
  });
});
