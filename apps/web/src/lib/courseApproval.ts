import { api } from '@/lib/api';

export type ApprovalDeliveryMode = 'email' | 'personal_link';
export type ApprovalOutcome = 'pending' | 'approved' | 'changes_requested' | 'cancelled' | 'superseded';
export type ReviewActivityState = 'not_started' | 'in_progress' | 'completed' | 'decision_pending';

export interface ApprovalCourseOption { id: string; title: string; requires_approval?: boolean }
const APPROVAL_COURSE_PAGE_SIZE = 100;
const APPROVAL_COURSE_MAX_PAGES = 50;

/** Load the bounded course catalog using the API's `per_page <= 100` contract. */
export async function listApprovalCourses(): Promise<ApprovalCourseOption[]> {
  const courses: ApprovalCourseOption[] = [];
  for (let page = 1; page <= APPROVAL_COURSE_MAX_PAGES; page += 1) {
    const response = await api.get<ApprovalCourseOption[] | { items?: ApprovalCourseOption[] }>(`/v1/courses?page=${page}&per_page=${APPROVAL_COURSE_PAGE_SIZE}`);
    const rows = Array.isArray(response.data) ? response.data : response.data.items || [];
    courses.push(...rows);
    if (rows.length < APPROVAL_COURSE_PAGE_SIZE) break;
  }
  return courses;
}

export interface ApprovalPolicy {
  course_id: string;
  requires_approval: boolean;
  review_enabled: boolean;
  updated_at?: string | null;
}

export interface ApprovalRevision {
  id: string;
  course_id: string;
  revision_number: number;
  snapshot_sha256: string;
  state: string;
  created_at: string;
}

export interface ApprovalRequestSummary {
  request_id: string;
  revision_id: string;
  outcome: ApprovalOutcome;
  delivery_mode: ApprovalDeliveryMode;
  reviewer_ids?: string[];
  due_at?: string | null;
  revision_number?: number;
  snapshot_sha256?: string;
  reviewers?: ReviewerApprovalStatus[];
  reviewer_count?: number;
  work_items?: ReviewerApprovalStatus[];
  deliveries?: DeliveryStatus[];
  progress?: ReviewProgressStatus[];
  all_required_approved?: boolean;
}

export type DeliveryState = 'queued' | 'accepted' | 'delivered' | 'failed' | 'terminal';
export interface DeliveryStatus { channel: 'cabinet' | 'email'; status: DeliveryState; attempt_count: number; error_category?: string | null }
export interface ReviewProgressStatus { attempt_id: string; activity_state: ReviewActivityState; lesson_position?: number | null; diagnostics?: ReviewDiagnostic | null; }
export interface ReviewDiagnostic { answered: number; total: number; correct: number; score_percent: number; complete: boolean; passed?: boolean }

export interface ReviewerApprovalStatus {
  reviewer_id?: string;
  id?: string;
  decision?: 'pending' | 'approved' | 'changes_requested';
  decision_at?: string | null;
  required?: boolean;
  delivery_state?: DeliveryState;
  access_state?: 'issued' | 'opened' | 'pin_verified' | 'active' | 'expired' | 'revoked';
  activity_state?: 'not_started' | 'in_progress' | 'completed' | 'decision_pending';
  deadline_state?: 'unset' | 'scheduled' | 'due' | 'overdue' | 'closed';
  outcome?: ApprovalOutcome;
  progress?: number | null;
}

export interface ReviewerAccessSecret {
  reviewer_id: string;
  access_url: string;
  temporary_pin: string;
  expires_at: string;
}

export interface ApprovalRequestResponse extends ApprovalRequestSummary {
  access_url?: string | null;
  temporary_pin?: string | null;
  access_credentials?: ReviewerAccessSecret[];
}

export interface ReviewChoice {
  id: string;
  text: string;
  order_index: number;
}

export interface ReviewQuestion {
  id: string;
  text: string;
  type: string;
  points: number;
  explanation?: string | null;
  order_index: number;
  choices: ReviewChoice[];
}

export interface ReviewQuiz {
  id: string;
  title: string;
  pass_score: number;
  time_limit?: number | null;
  attempt_limit?: number | null;
  questions: ReviewQuestion[];
}

export interface ReviewLesson {
  id: string;
  title: string;
  content_type: string;
  content?: string | null;
  order_index: number;
  quizzes: ReviewQuiz[];
}

export interface ReviewModule {
  id: string;
  title: string;
  description?: string | null;
  order_index: number;
  lessons: ReviewLesson[];
}

export interface ReviewSnapshot {
  schema_version: number;
  release_version: number;
  course: { id: string; title: string; description?: string | null };
  modules: ReviewModule[];
}

export interface ReviewAttempt {
  attempt_id: string;
  revision_id: string;
  snapshot_sha256: string;
  activity_state: ReviewActivityState;
  lesson_position?: number | null;
  snapshot: ReviewSnapshot;
}

export interface ReviewDecisionResponse {
  revision_id: string;
  decision: 'approve' | 'return';
  outcome: ApprovalOutcome;
  activity_state: ReviewActivityState;
}

export interface ReviewProgressResponse {
  attempt_id?: string;
  activity_state?: ReviewActivityState;
  lesson_position?: number | null;
  diagnostics?: ReviewDiagnostic;
  result?: ReviewDiagnostic;
}

function reviewConfig(token?: string) {
  const effectiveToken = token || (typeof window !== 'undefined' ? sessionStorage.getItem('course_review_token') : null);
  return effectiveToken ? { headers: { Authorization: `Bearer ${effectiveToken}` } } : undefined;
}

export async function configureApprovalPolicy(courseId: string, requiresApproval: boolean): Promise<ApprovalPolicy> {
  const response = await api.patch<ApprovalPolicy>(`/v1/courses/${courseId}/approval-policy`, { requires_approval: requiresApproval, review_enabled: true });
  return response.data;
}

export async function freezeApprovalRevision(courseId: string): Promise<ApprovalRevision> {
  const response = await api.post<ApprovalRevision>(`/v1/courses/${courseId}/approval-revisions`);
  return response.data;
}

export async function listApprovalRevisions(courseId: string): Promise<ApprovalRevision[]> {
  const response = await api.get<ApprovalRevision[]>(`/v1/courses/${courseId}/approval-revisions`);
  return response.data;
}

export interface GuestReviewerInput { email: string; name?: string }

export async function createApprovalRequest(revisionId: string, reviewerUserIds: string[], deliveryMode: ApprovalDeliveryMode, dueAt?: string, guestReviewers: GuestReviewerInput[] = []): Promise<ApprovalRequestResponse> {
  const response = await api.post<ApprovalRequestResponse>(`/v1/course-approval-revisions/${revisionId}/requests`, {
    reviewer_user_ids: reviewerUserIds,
    guest_reviewers: guestReviewers,
    delivery_mode: deliveryMode,
    ...(dueAt ? { due_at: dueAt } : {}),
  });
  return response.data;
}

export async function listApprovalRequests(_token?: string): Promise<ApprovalRequestSummary[]> {
  const response = await api.get<ApprovalRequestSummary[]>('/v1/course-approval-requests');
  return response.data;
}

export async function getApprovalRequest(requestId: string, _token?: string): Promise<ApprovalRequestSummary> {
  const response = await api.get<ApprovalRequestSummary>(`/v1/course-approval-requests/${requestId}`);
  return response.data;
}

export interface ScopedReviewRequest {
  request_id: string;
  revision_id: string;
  outcome: ApprovalOutcome;
  delivery_mode: ApprovalDeliveryMode;
  due_at?: string | null;
  reviewer: ReviewerApprovalStatus;
  all_required_approved: boolean;
}

/** The scoped endpoint is intentionally separate from the tenant requester projection. */
export async function getScopedReviewRequest(token?: string, requestId?: string): Promise<ScopedReviewRequest> {
  const path = requestId ? `/v1/course-review-requests/${encodeURIComponent(requestId)}` : '/v1/course-review-requests';
  const response = await api.get<ScopedReviewRequest>(path, reviewConfig(token));
  return response.data;
}

export async function cancelApprovalRequest(requestId: string): Promise<void> {
  await api.post(`/v1/course-approval-requests/${requestId}/cancel`);
}

export async function revokeApprovalAccess(requestId: string): Promise<void> {
  await api.post(`/v1/course-approval-requests/${requestId}/revoke`);
}

export interface ResendApprovalResponse { request_id: string; rotated: boolean; retried: number; access_credentials: ReviewerAccessSecret[] }

export async function resendApprovalDelivery(requestId: string, rotateCredentials = false): Promise<ResendApprovalResponse> {
  const response = await api.post<ResendApprovalResponse>(`/v1/course-approval-requests/${requestId}/resend`, { rotate_credentials: rotateCredentials });
  return response.data;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function containsAnswerKey(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsAnswerKey);
  if (!isRecord(value)) return false;
  if ('is_correct' in value || 'correct_choice_id' in value || 'answer_key' in value) return true;
  return Object.values(value).some(containsAnswerKey);
}

/** Project the frozen release snapshot into a reviewer-safe DTO (never expose answer keys). */
export function projectReviewSnapshot(value: unknown): ReviewSnapshot {
  if (!isRecord(value)) throw new Error('Некорректный снимок курса');
  const course = isRecord(value.course) ? value.course : {};
  const modules = Array.isArray(value.modules) ? value.modules : [];
  return {
    schema_version: numberValue(value.schema_version, 1),
    release_version: numberValue(value.release_version, 1),
    course: { id: stringValue(course.id), title: stringValue(course.title, 'Курс'), description: typeof course.description === 'string' ? course.description : null },
    modules: modules.filter(isRecord).map((module) => ({
      id: stringValue(module.id),
      title: stringValue(module.title, 'Модуль'),
      description: typeof module.description === 'string' ? module.description : null,
      order_index: numberValue(module.order_index),
      lessons: (Array.isArray(module.lessons) ? module.lessons : []).filter(isRecord).map((lesson) => ({
        id: stringValue(lesson.id),
        title: stringValue(lesson.title, 'Урок'),
        content_type: stringValue(lesson.content_type, 'text'),
        content: typeof lesson.content === 'string' ? lesson.content : null,
        order_index: numberValue(lesson.order_index),
        quizzes: (Array.isArray(lesson.quizzes) ? lesson.quizzes : []).filter(isRecord).map((quiz) => ({
          id: stringValue(quiz.id),
          title: stringValue(quiz.title, 'Тест'),
          pass_score: numberValue(quiz.pass_score),
          time_limit: typeof quiz.time_limit === 'number' ? quiz.time_limit : null,
          attempt_limit: typeof quiz.attempt_limit === 'number' ? quiz.attempt_limit : null,
          questions: (Array.isArray(quiz.questions) ? quiz.questions : []).filter(isRecord).map((question) => ({
            id: stringValue(question.id),
            text: stringValue(question.text),
            type: stringValue(question.type, 'single_choice'),
            points: numberValue(question.points, 1),
            explanation: typeof question.explanation === 'string' ? question.explanation : null,
            order_index: numberValue(question.order_index),
            choices: (Array.isArray(question.choices) ? question.choices : []).filter(isRecord).map((choice) => ({
              id: stringValue(choice.id),
              text: stringValue(choice.text),
              order_index: numberValue(choice.order_index),
            })),
          })),
        })),
      })),
    })),
  };
}

export async function startReviewAttempt(requestId: string, token?: string): Promise<ReviewAttempt> {
  const response = await api.post<Record<string, unknown>>(`/v1/course-approval-requests/${requestId}/attempts`, undefined, reviewConfig(token));
  const body = response.data;
  if (!isRecord(body) || typeof body.attempt_id !== 'string' || typeof body.revision_id !== 'string' || typeof body.snapshot_sha256 !== 'string') {
    throw new Error('Сервер вернул неполный снимок курса');
  }
  if (containsAnswerKey(body.snapshot)) throw new Error('Сервер вернул небезопасный снимок с ключом ответа');
  const activity = body.activity_state;
  if (activity !== 'not_started' && activity !== 'in_progress' && activity !== 'completed' && activity !== 'decision_pending') {
    throw new Error('Неизвестное состояние проверки');
  }
  return {
    attempt_id: body.attempt_id,
    revision_id: body.revision_id,
    snapshot_sha256: body.snapshot_sha256,
    activity_state: activity,
    lesson_position: typeof body.lesson_position === 'number' ? body.lesson_position : null,
    snapshot: projectReviewSnapshot(body.snapshot),
  };
}

export async function saveReviewProgress(attemptId: string, sequence: number, lessonPosition: number | null, activityState: Exclude<ReviewActivityState, 'decision_pending'>, payload: Record<string, unknown> = {}, token?: string, eventType?: string): Promise<ReviewProgressResponse> {
  const response = await api.put<ReviewProgressResponse>(`/v1/course-review-attempts/${attemptId}/progress`, {
    sequence,
    lesson_position: lessonPosition,
    event_type: eventType || (activityState === 'completed' ? 'review_completed' : 'review_activity'),
    payload: { purpose: 'course_review', ...payload },
    activity_state: activityState,
  }, reviewConfig(token));
  return response.data;
}

export async function submitReviewTest(attemptId: string, submissions: Array<{ question_id: string; selected_choice_ids: string[] }>, token?: string): Promise<ReviewProgressResponse> {
  const response = await api.post<ReviewProgressResponse>(`/v1/course-review-attempts/${attemptId}/test`, submissions, reviewConfig(token));
  return response.data;
}

export async function submitReviewDecision(attemptId: string, decision: 'approve' | 'return', reason: string | null, acknowledgeIncompleteWarning: boolean, token?: string): Promise<ReviewDecisionResponse> {
  const response = await api.post<ReviewDecisionResponse>(`/v1/course-review-attempts/${attemptId}/decision`, {
    decision,
    reason,
    acknowledge_incomplete_warning: acknowledgeIncompleteWarning,
  }, reviewConfig(token));
  return response.data;
}

export async function verifyReviewPin(token: string, pin: string): Promise<{ review_token: string; work_item_id: string; request_id?: string; revision_id?: string }> {
  const response = await api.post<{ review_token: string; work_item_id: string; request_id?: string; revision_id?: string }>(`/v1/course-review-access/${encodeURIComponent(token)}/verify-pin`, { pin });
  return response.data;
}
