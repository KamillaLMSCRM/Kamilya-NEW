import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('legacy quiz assignment route', () => {
  it('redirects to the quiz builder because lesson tests follow course access', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/app/admin/quizzes/assign/page.tsx'),
      'utf8',
    );

    expect(source).toContain("redirect('/quizzes')");
    expect(source).not.toContain('section=assignments');
    expect(source).not.toContain('QuizAssignPanel');
  });
});
