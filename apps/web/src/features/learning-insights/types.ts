export type ReviewStatus = 'unreviewed' | 'train_staff' | 'review_question' | 'improve_material' | 'resolved';

export interface Review { status: ReviewStatus; updated_at: string | null; }
export interface ChoiceDetail { id: string; text: string; selected: boolean; correct: boolean; }
export interface QuestionDetail { question_id: string; question_key: string; text: string; type: string; explanation: string | null; is_correct: boolean; points_earned: number; points_possible: number; choices: ChoiceDetail[]; review: Review; }
export interface AttemptDetail { id: string; quiz_id: string; quiz_title: string; content_release_id: string | null; completed_at: string; attempt_number: number; score_percent: number; passed: boolean; evidence_status: 'verified' | 'unavailable' | 'invalid'; lesson_id: string | null; questions: QuestionDetail[]; }
export interface EnrollmentInsights { enrollment_id: string; user_name: string; course_id: string; course_title: string; attempts: AttemptDetail[]; }
export interface QuestionStats { question_key: string; question_id: string; quiz_id: string; quiz_title: string; content_release_id: string | null; text: string; lesson_id: string | null; respondents: number; incorrect: number; incorrect_percent: number; latest_respondents: number; latest_unavailable: number; latest_incorrect: number; latest_incorrect_percent: number | null; improved: number; regressed: number; wrong_choices: Array<{ id: string; text: string; count: number }>; review: Review; example_attempt_id: string; }
export interface CourseInsights { course_id: string; course_title: string; cohort_basis: 'current_structure'; attempt_basis: 'first_completed'; included_employees: number; excluded_attempts: number; questions: QuestionStats[]; }
export interface LearningInsightsFilters { departmentId?: string; positionId?: string; dateFrom?: string; dateTo?: string; }
