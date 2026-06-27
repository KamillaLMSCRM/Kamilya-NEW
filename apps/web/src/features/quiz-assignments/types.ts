/**
 * Quiz Assignments — TypeScript types.
 * Mirrors backend `app.modules.quizzes.assignment_schemas`.
 */

export type AssignmentStatus = 'assigned' | 'completed' | 'overdue';

export interface QuizAssignment {
  id: string;
  quiz_id: string;
  quiz_title: string | null;
  user_id: string;
  user_name: string | null;
  user_email: string | null;
  assigned_by: string;
  due_date: string | null;
  status: string;
  score_percent: number | null;
  completed_at: string | null;
  created_at: string | null;
  /** Set when assignment was created via /by-positions and the user's
   * position hasn't changed since. Backend re-queries users.position_id
   * at GET time, so this reflects the user's CURRENT position. */
  position_id: string | null;
  position_name: string | null;
}

export interface AssignmentCreateResult {
  created: number;
  skipped: number;
}

export interface PositionAssignmentSummary {
  positions_requested: number;
  users_targeted: number;
  users_assigned: number;
  users_skipped: number;
  positions_not_found: string[];
}

/** Position as returned by /v1/positions — minimal shape for assignment UI. */
export interface PositionLite {
  id: string;
  name: string;
  department: string;
  /** Cached count from positions.employee_count (may be stale). */
  employee_count: number;
  /** Always-fresh count from JOIN to users table. Prefer this for UI display. */
  current_employee_count: number;
  /** True when cached != live. UI can show a "↻" badge. */
  employee_count_stale: boolean;
}