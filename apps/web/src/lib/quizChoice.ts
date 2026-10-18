export function isSingleAnswerQuestionType(type: string): boolean {
  return type === 'MCQ' || type === 'true_false' || type === 'single_choice';
}
