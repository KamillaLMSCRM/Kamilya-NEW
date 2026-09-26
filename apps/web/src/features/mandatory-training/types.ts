export type RequirementState =
  | 'materialized'
  | 'missing_enrollment'
  | 'protected_assignment'
  | 'stale_managed_enrollment';

export type RequirementAction = 'none' | 'materialize' | 'review_stale';

export interface AssignmentReason {
  kind: 'position' | 'department' | 'organization' | 'manual' | 'cohort' | 'learning_path' | 'recurring' | 'auto' | 'unknown';
  source_ref_id: string | null;
  source_name: string | null;
  scope_path_ids: string[];
  scope_path_names: string[];
  reason_code: string;
}

export interface MandatoryTrainingRow {
  user_id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
  organization_unit_id: string | null;
  organization_unit_path: string[];
  position_id: string | null;
  position_name: string | null;
  course_id: string;
  course_title: string;
  delivery_type: 'native' | 'scorm';
  requirement_state: RequirementState;
  assignment_reason: AssignmentReason;
  action_required: RequirementAction;
  enrollment_id: string | null;
  enrollment_source: string | null;
  enrollment_status: string | null;
  computed_status: 'assigned' | 'in_progress' | 'completed' | 'cancelled' | 'superseded' | null;
  progress_percent: number | null;
  assignment_due_at: string | null;
  deadline_state: 'none' | 'upcoming' | 'overdue' | 'completed_on_time' | 'completed_late' | null;
  deadline_status: 'not_applicable' | 'active' | 'overdue' | 'completed_on_time' | 'completed_late' | null;
  certificate_status: 'none' | 'active' | 'expiring' | 'expired' | 'revoked' | null;
  latest_evidence_event_id: string | null;
  evidence_confirmation_status: 'not_required' | 'pending' | 'confirmed' | null;
  evidence_signed_copy_status: 'awaiting_return' | 'uploaded_pending_review' | 'accepted' | 'replacement_requested' | null;
  evidence_state: 'forming' | 'ready' | 'incomplete' | 'revoked' | 'legal_hold' | null;
}

export interface MandatoryTrainingPage {
  items: MandatoryTrainingRow[];
  total: number;
  limit: number;
  offset: number;
  reporting_scope: 'tenant' | 'restricted';
}

export interface MandatoryTrainingSummary {
  total: number;
  materialized: number;
  missing_enrollment: number;
  protected_assignment: number;
  stale_managed_enrollment: number;
  action_materialize: number;
  action_review_stale: number;
}
