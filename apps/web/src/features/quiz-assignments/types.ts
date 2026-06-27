/**
 * Quiz Assignments — TypeScript types.
 * Mirrors backend `app.modules.quizzes.assignment_schemas.QuizAssignmentResponse`.
 */

export type AssignmentStatus = 'assigned' | 'completed' | 'overdue';

export interface QuizAssignment {
  id: string;
  quiz_id: string;
  quiz_title: string | null;
  user_id: string;
  user_name: string | null;
  status: string;
  score_percent: number | null;
  due_date: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface AssignmentCreateResult {
  created: number;
  skipped: number;
}