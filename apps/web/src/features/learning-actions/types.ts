export type LearningIssueType =
  | 'not_started'
  | 'stalled'
  | 'overdue'
  | 'failed_required_quiz'
  | 'weak_question';
export type LearningActionType = 'reminder' | 'reassignment' | 'supplemental_material' | 'manual_review';
export type LearningActionStatus = 'open' | 'completed' | 'cancelled';
export type LearningActionTargetType = 'enrollment' | 'question';
export type LearningActionResolution = 'observed' | 'manual' | 'cancelled';

export interface LearningAction {
  id: string;
  tenant_id: string;
  target_type: LearningActionTargetType;
  target_key: string;
  enrollment_id: string | null;
  course_id: string;
  quiz_id: string | null;
  content_release_id: string | null;
  question_id: string | null;
  question_key: string | null;
  issue_type: LearningIssueType;
  action_type: LearningActionType;
  status: LearningActionStatus;
  owner_id: string | null;
  created_by: string | null;
  due_at: string | null;
  comment: string | null;
  baseline_snapshot: Record<string, unknown>;
  outcome_snapshot: Record<string, unknown> | null;
  resolution: LearningActionResolution | null;
  resolution_note: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface TrainingAttentionItem {
  enrollment_id: string;
  user_id: string;
  full_name: string;
  course_id: string;
  course_title: string;
  issue_type: Exclude<LearningIssueType, 'weak_question'>;
  progress_percent: number;
  best_score: number | null;
  quiz_attempts_count: number;
  assignment_due_at: string | null;
  active_action_id: string | null;
  active_action_types: LearningActionType[];
}

export interface WeakQuestionItem {
  question_key: string;
  question_id: string;
  quiz_id: string;
  content_release_id: string | null;
  text: string;
  quiz_title: string;
  respondents: number;
  incorrect_percent: number;
  active_action_id: string | null;
  active_action_types: LearningActionType[];
}

export interface LearningActionCenterPayload {
  summary: {
    training_issue_count: number;
    training_issue_counts: Record<string, number>;
    training_items_truncated: boolean;
    weak_question_count: number;
    action_count: number;
    actions_truncated: boolean;
    open_action_count: number;
    overdue_action_count: number;
  };
  training_items: TrainingAttentionItem[];
  weak_questions: WeakQuestionItem[];
  actions: LearningAction[];
}

export interface CreateLearningAction {
  target_type: LearningActionTargetType;
  enrollment_id?: string;
  course_id?: string;
  quiz_id?: string;
  content_release_id?: string | null;
  question_id?: string;
  question_key?: string;
  issue_type: LearningIssueType;
  action_type: LearningActionType;
  due_at?: string | null;
  comment?: string | null;
}
