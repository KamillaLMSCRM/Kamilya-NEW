export const ACTION_FOCUS_VALUES = ['training', 'weak_questions', 'open', 'overdue'] as const;
export type ActionFocus = (typeof ACTION_FOCUS_VALUES)[number];

export const ACTION_ISSUE_TYPES = [
  'not_started',
  'stalled',
  'overdue',
  'failed_required_quiz',
] as const;
export type ActionIssueType = (typeof ACTION_ISSUE_TYPES)[number];

export function parseActionFocus(value: string | null): ActionFocus | undefined {
  return value && (ACTION_FOCUS_VALUES as readonly string[]).includes(value)
    ? value as ActionFocus
    : undefined;
}

export function parseActionIssueType(value: string | null): ActionIssueType | undefined {
  return value && (ACTION_ISSUE_TYPES as readonly string[]).includes(value)
    ? value as ActionIssueType
    : undefined;
}
