export type QualificationTab = "profile" | "instruction" | "competencies" | "training" | "onboarding" | "history";

export interface PositionProfile {
  id: string;
  tenant_id: string;
  name: string;
  department: string | null;
  level: string;
  responsibilities: string;
  requirements: string;
  employee_count: number;
  current_employee_count: number;
  created_at: string | null;
}

export interface InstructionSummary {
  document_id: string;
  filename: string;
  index_status: "processing" | "ready" | "partial" | "failed";
  index_error_code: string | null;
  updated_at: string | null;
  version: number;
}

export interface PositionCompetencyItem {
  id: string;
  name: string;
  description: string;
  required_level: number;
  course_ids: string[];
}

export interface CourseRule {
  course_id: string;
  title: string;
  status: string;
  required: boolean;
  source: "position" | "department" | "competency";
}

export interface EffectiveCourse {
  course_id: string;
  title: string;
  status: string;
  required: boolean;
  sources: Array<"position" | "department" | "competency">;
}

export interface PositionTrainingSummary {
  position_courses: CourseRule[];
  department_courses: CourseRule[];
  competency_courses: CourseRule[];
  effective_courses: EffectiveCourse[];
}

export interface QuizChoiceDraft {
  text: string;
  is_correct: boolean;
}

export interface QuizQuestionDraft {
  text: string;
  type: string;
  explanation: string;
  choices: QuizChoiceDraft[];
}

export interface OnboardingQuizSummary {
  id: string;
  title: string;
  pass_score: number;
  time_limit: number | null;
  is_active: boolean;
  question_count: number;
  questions: QuizQuestionDraft[];
  updated_at: string | null;
}

export interface PositionQualificationCardData {
  profile: PositionProfile;
  instruction: InstructionSummary | null;
  competencies: PositionCompetencyItem[];
  training: PositionTrainingSummary;
  onboarding_quiz: OnboardingQuizSummary | null;
  employees: {
    active_count: number;
  };
  latest_version: number | null;
  history_count: number;
}

export interface QualificationHistoryItem {
  id: string;
  version_no: number;
  change_kind: string;
  change_reason: string | null;
  created_by: string | null;
  created_at: string;
}

export interface CompetencyCatalogItem {
  id: string;
  name: string;
  description: string;
  position_count?: number;
  course_count?: number;
}

export interface CourseCatalogItem {
  id: string;
  title: string;
  status: string;
}
