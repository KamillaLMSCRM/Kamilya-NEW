import type { TranslationKey } from '@/i18n/useT';

const approvalMessages: Record<string, TranslationKey> = {
  course_content_required: 'courses.contentRequired',
  source_uncertainty_review_required: 'nextCourseAction.courseSource',
  quiz_review_required: 'nextCourseAction.quizReview',
  course_languages_review_required: 'nextCourseAction.languageReview',
  approval_required: 'courseApproval.publishRequiresApproval',
  approval_pending: 'courseApproval.publishApprovalPending',
  approval_changes_requested: 'courseApproval.publishChangesRequested',
  approval_superseded: 'courseApproval.publishRevisionChanged',
  approval_revision_mismatch: 'courseApproval.publishRevisionChanged',
};

/** Read the structured API code before its generic/stringified message. */
export function coursePublicationError(payload: unknown, t: (key: TranslationKey) => string): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined;
  const body = payload as Record<string, unknown>;
  const detail = body.details ?? body.detail;
  if (!detail || typeof detail !== 'object') return undefined;
  const code = (detail as Record<string, unknown>).code;
  const key = typeof code === 'string' && Object.hasOwn(approvalMessages, code) ? approvalMessages[code] : undefined;
  return key ? t(key) : undefined;
}
