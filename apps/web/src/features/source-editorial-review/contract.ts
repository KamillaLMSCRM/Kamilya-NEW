export type SourceReviewStatus = 'not_started' | 'queued' | 'running' | 'interrupted' | 'failed' | 'in_review' | 'approved' | 'source_changed';

export interface SourceReviewPin {
  document_id: string;
  approval_id: string;
  revision: number;
  working_sha256: string;
}

interface Change {
  id: string;
  start: number | null;
  end: number | null;
  before: string;
  after: string;
  reason: string;
}

export interface SourceQuestion {
  id: string;
  quote: string;
  reason: string;
  start: number | null;
  end: number | null;
  needs_source_verification?: boolean;
  resolution: (Change & { decision: 'replace' | 'keep' }) | null;
}

export type ReviewPages = { first_page: number; last_page: number };

export interface SourceReview {
  document_id: string;
  document_version: number;
  title: string;
  revision: number;
  status: SourceReviewStatus;
  error: string | null;
  pdf?: boolean;
  pages?: ReviewPages | null;
  questions: SourceQuestion[];
  automatic: Array<Change & { undone: boolean }>;
  original_text: string | null;
  working_text: string | null;
  approval: (SourceReviewPin & { created_at: string }) | null;
  journal: Array<Partial<Change> & {
    id: string; item_id?: string; kind: string; revision: number; actor_id: string | null; created_at: string;
  }>;
}

export interface ReviewCommand {
  expected_revision: number;
  request_id: string;
  action: 'start' | 'resolve' | 'reopen_issue' | 'undo_auto' | 'approve' | 'reopen' | 'add_edit';
  item_id?: string;
  decision?: 'replace' | 'keep';
  replacement?: string;
  quote?: string;
  reason?: string;
  pages?: ReviewPages;
}

export const sourceReviewHref = (id: string, approvalId?: string) =>
  `/documents/${encodeURIComponent(id)}/editorial-review${approvalId ? '/' + encodeURIComponent(approvalId) : ''}`;

export function sourceReviewPins(value: unknown): SourceReviewPin[] {
  if (!Array.isArray(value)) return [];
  const uuid = /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i;
  return value.filter((x): x is SourceReviewPin => x && typeof x === 'object'
    && typeof x.document_id === 'string' && uuid.test(x.document_id)
    && typeof x.approval_id === 'string' && uuid.test(x.approval_id)
    && Number.isInteger(x.revision) && typeof x.working_sha256 === 'string');
}
