import { sameAuthorSession, type AuthorSessionScope } from '@/features/course-authoring/authorSession';

export type QuestionDraftScope = AuthorSessionScope;

export type QuestionEditorSnapshot = {
  text: string; type: string; points: number; explanation: string; order_index?: number;
  choices: Array<{ id?: string; text: string; is_correct: boolean; order_index?: number }>;
};

export type RetainedQuestionDraft = {
  quizId: string; questionId: string | null; mode: 'create' | 'edit';
  question: Omit<QuestionEditorSnapshot, 'choices' | 'order_index'>;
  choices: QuestionEditorSnapshot['choices'];
  savedSnapshot: QuestionEditorSnapshot;
};

// One volatile unsaved editor, never a saved-content authority. It survives
// same-document client/history route unmounts, not reloads or session changes.
let retained: { scope: QuestionDraftScope; draft: RetainedQuestionDraft } | null = null;

export function sameQuestionDraftScope(left: QuestionDraftScope, right: QuestionDraftScope) {
  return sameAuthorSession(left, right);
}

export function sameSavedQuestion(left: QuestionEditorSnapshot, right: QuestionEditorSnapshot) {
  return left.text === right.text && left.type === right.type && left.points === right.points
    && left.explanation === right.explanation && left.order_index === right.order_index
    && left.choices.length === right.choices.length && left.choices.every((choice, index) => {
      const other = right.choices[index];
      return choice.id === other.id && choice.text === other.text && choice.is_correct === other.is_correct && choice.order_index === other.order_index;
    });
}

export function retainQuestionDraft(scope: QuestionDraftScope, draft: RetainedQuestionDraft) {
  retained = { scope: { ...scope }, draft };
}

export function readQuestionDraft(scope: QuestionDraftScope): RetainedQuestionDraft | null {
  return retained && sameQuestionDraftScope(retained.scope, scope) ? retained.draft : null;
}

export function clearQuestionDraft(scope?: QuestionDraftScope, expected?: RetainedQuestionDraft | null) {
  if (expected !== undefined && retained?.draft !== expected) return;
  if (!scope || (retained && sameQuestionDraftScope(retained.scope, scope))) retained = null;
}

export function bindQuestionDraftScope(scope: QuestionDraftScope) {
  if (retained && !sameQuestionDraftScope(retained.scope, scope)) retained = null;
}
