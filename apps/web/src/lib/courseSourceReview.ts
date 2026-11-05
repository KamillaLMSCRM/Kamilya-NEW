/** Ordinary methodologist inspection and explicit, revision-bound resolution. */
export interface DraftReviewItem {
  id: string; kind: string; target_id: string; message: string;
  source_refs: string[]; blocking: boolean;
}
export interface DraftReview {
  version: string; generation_status: 'draft_prepared';
  self_review_status: 'passed' | 'needs_attention'; human_review_required: true;
  issues: DraftReviewItem[]; observations: DraftReviewItem[];
}
export interface SourceReviewDetails {
  course_id: string; has_active_hold: boolean; content_snapshot_hash: string;
  available_revisions: string[];
  source_documents: { document_id: string; title: string; filename: string; authoritative_revision: string }[];
  active_defects: { defect_id: string; description: string; target_id?: string; target_title?: string;
    evidence?: { unverified?: boolean; observation?: string; missing_condition?: string;
      possible_answers?: string[]; source_quotes?: string[] } }[];
  resolutions_history: { resolved_at?: string; reason?: string }[];
  draft_review?: DraftReview | null;
}
export interface SourceReviewResolution {
  reason: string; expected_content_hash: string; verified_revision: string;
  verified_revisions: Record<string, string>;
  defect_resolutions: { defect_id: string; action: 'manual_verification_passed'; rationale: string }[];
}
export class SourceReviewError extends Error {
  constructor(public status: number, public unknownOutcome = false) { super('source_review_request_failed'); }
}

async function request(courseId: string, token: string, signal: AbortSignal, body?: SourceReviewResolution): Promise<unknown> {
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base || !token || !courseId) throw new SourceReviewError(0);
  let response: Response;
  try {
    response = await fetch(`${base}/v1/courses/${encodeURIComponent(courseId)}/${body ? 'resolve-source-uncertainty' : 'source-uncertainty'}`, {
      method: body ? 'POST' : 'GET', signal,
      headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch { throw new SourceReviewError(0, Boolean(body)); }
  if (!response.ok) throw new SourceReviewError(response.status);
  try { return await response.json(); } catch { throw new SourceReviewError(0, Boolean(body)); }
}

export async function inspectCourseSource(courseId: string, token: string, signal: AbortSignal): Promise<SourceReviewDetails> {
  const value = await request(courseId, token, signal) as SourceReviewDetails;
  if (!value || value.course_id !== courseId || !/^[a-f0-9]{64}$/.test(value.content_snapshot_hash)
    || typeof value.has_active_hold !== 'boolean' || !Array.isArray(value.active_defects)
    || !Array.isArray(value.source_documents) || !Array.isArray(value.available_revisions)
    || !Array.isArray(value.resolutions_history)
    || value.active_defects.some((row) => !row || typeof row.defect_id !== 'string' || typeof row.description !== 'string')
    || value.active_defects.some((row) => (row.target_title != null && typeof row.target_title !== 'string')
      || (row.evidence != null && (typeof row.evidence !== 'object'
        || (row.evidence.observation != null && typeof row.evidence.observation !== 'string')
        || (row.evidence.missing_condition != null && typeof row.evidence.missing_condition !== 'string')
        || [row.evidence.possible_answers, row.evidence.source_quotes].some((items) => items != null
          && (!Array.isArray(items) || items.some((item) => typeof item !== 'string'))))))
    || new Set(value.active_defects.map((row) => row.defect_id)).size !== value.active_defects.length
    || value.source_documents.some((row) => !row || typeof row.document_id !== 'string' || typeof row.authoritative_revision !== 'string')
    || value.available_revisions.some((row) => typeof row !== 'string')
    || (value.draft_review != null && (value.draft_review.version !== 'p30-editorial-draft-v1'
      || !['passed', 'needs_attention'].includes(value.draft_review.self_review_status)
      || !Array.isArray(value.draft_review.issues) || !Array.isArray(value.draft_review.observations)
      || [...value.draft_review.issues, ...value.draft_review.observations].some((row) => !row
        || typeof row.id !== 'string' || typeof row.message !== 'string')))) throw new SourceReviewError(0);
  return value;
}

export async function resolveCourseSource(courseId: string, token: string, signal: AbortSignal, body: SourceReviewResolution): Promise<void> {
  const value = await request(courseId, token, signal, body) as { id?: string };
  if (!value || value.id !== courseId) throw new SourceReviewError(0, true);
}
