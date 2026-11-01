import { describe, expect, it } from 'vitest';
import { authorSessionScope, sameAuthorSession } from '@/features/course-authoring/authorSession';
import { retainQuestionDraft, readQuestionDraft } from '@/features/quiz-authoring/questionDraft';

describe('author session boundaries', () => {
  it('keeps token refresh but rejects explicit replacement and impersonation changes', () => {
    const user = { user_id: 'author', tenant_id: 'tenant', role: 'methodologist', impersonated_by: 'admin-a', impersonated_role: 'admin' };
    const first = authorSessionScope({ accessToken: 'old', user, sessionEpoch: 1 });
    retainQuestionDraft(first, { quizId: 'q', questionId: null, mode: 'create', question: { text: 'private', type: 'MCQ', points: 1, explanation: '' }, choices: [], savedSnapshot: { text: '', type: 'MCQ', points: 1, explanation: '', choices: [] } });
    const refresh = authorSessionScope({ accessToken: 'new', user, sessionEpoch: 1 });
    expect(sameAuthorSession(first, refresh)).toBe(true);
    expect(readQuestionDraft(refresh)?.question.text).toBe('private');
    const replacement = authorSessionScope({ accessToken: 'new', user, sessionEpoch: 2 });
    expect(sameAuthorSession(first, replacement)).toBe(false);
    expect(readQuestionDraft(replacement)).toBeNull();
    const otherImpersonator = authorSessionScope({ accessToken: 'new', user: { ...user, impersonated_by: 'admin-b' }, sessionEpoch: 2 });
    expect(sameAuthorSession(replacement, otherImpersonator)).toBe(false);
    const otherRole = authorSessionScope({ accessToken: 'new', user: { ...user, impersonated_by: 'admin-b', impersonated_role: 'support' }, sessionEpoch: 2 });
    expect(sameAuthorSession(otherImpersonator, otherRole)).toBe(false);
  });
});
