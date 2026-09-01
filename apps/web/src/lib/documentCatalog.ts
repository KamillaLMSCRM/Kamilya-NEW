export type DocumentCategory = 'general' | 'job_instruction';
export type DocumentIndexStatus = 'processing' | 'ready' | 'partial' | 'failed';
export type DocumentLifecycleStatus = 'active' | 'deletion_pending' | 'delete_failed';

export interface DocumentCatalogItem {
  id: string;
  source_family_id: string;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  description: string;
  category: DocumentCategory;
  index: {
    status: DocumentIndexStatus;
    error_code: string | null;
    message: string | null;
    chunks_total: number | null;
    chunks_indexed: number | null;
    indexed_at: string | null;
    revision: number;
  };
  version: number;
  is_latest: boolean;
  lifecycle_status: DocumentLifecycleStatus;
  deletion_error_code: string | null;
  deletion_error_message: string | null;
  deletion_job_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  usages_summary?: {
    total: number;
    courses: number;
    positions: number;
    lessons: number;
    active_jobs: number;
  } | null;
}

export interface DocumentJobAccepted {
  document_id: string;
  job_id: string;
  status_url: string;
  revision?: number;
  index_status?: 'processing';
  lifecycle_status?: 'deletion_pending';
}

export interface DocumentCatalogResponse {
  items: DocumentCatalogItem[];
  page: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
  };
}

export interface DuplicateDocumentConflict {
  id: string;
  title: string;
  filename: string;
  version: number;
}

export type DocumentUsageType =
  | 'position_instruction'
  | 'course_instruction'
  | 'course_source'
  | 'lesson_source'
  | 'active_ai_job';

export interface DocumentUsageResponse {
  summary: {
    total: number;
    positions: number;
    courses: number;
    lessons: number;
    active_jobs: number;
  };
  items: Array<{
    type: DocumentUsageType;
    id: string;
    title: string;
    status: string | null;
    route: string;
    blocks_delete: boolean;
  }>;
  page: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
  };
}

export const isDocumentSelectable = (document: DocumentCatalogItem) =>
  document.lifecycle_status === 'active'
  && (document.index.status === 'ready' || document.index.status === 'partial');

const defaultObjectCount = (count: number) => {
  const forms = { one: 'объект', few: 'объекта', many: 'объектов', other: 'объекта' };
  const category = new Intl.PluralRules('ru').select(count);
  return `${count} ${forms[category as keyof typeof forms] ?? forms.other}`;
};

export const documentDeleteError = (
  error: any,
  formatObjectCount: (count: number) => string = defaultObjectCount
): string => {
  const detail = error?.response?.data?.details ?? error?.response?.data?.detail;
  if (detail?.code === 'document_in_use') {
    const count = Number(detail?.summary?.total || 0);
    return count > 0
      ? `Документ используется: ${formatObjectCount(count)}. Сначала отвяжите его от должностей, курсов, уроков или дождитесь завершения AI-задачи.`
      : 'Документ используется в других объектах.';
  }
  if (detail?.code === 'document_processing') {
    return 'Дождитесь окончания индексации документа и повторите удаление.';
  }
  if (detail?.code === 'cleanup_enqueue_failed') {
    return 'Сервис фоновой очистки временно недоступен. Повторите удаление позже.';
  }
  if (detail?.code === 'document_not_active') {
    return 'Операция доступна только для активного документа.';
  }
  if (detail?.code === 'document_in_active_job') {
    return 'Документ используется активной AI-задачей. Дождитесь её завершения.';
  }
  if (typeof detail === 'string') return detail;
  if (typeof detail?.message === 'string') return detail.message;
  return error?.message || 'Повторите попытку.';
};

export const getDuplicateDocumentConflict = (error: any): DuplicateDocumentConflict | null => {
  const detail = error?.response?.data?.details ?? error?.response?.data?.detail;
  const existing = detail?.code === 'duplicate_document' ? detail.existing : null;
  if (
    typeof existing?.id !== 'string'
    || typeof existing?.title !== 'string'
    || typeof existing?.filename !== 'string'
    || typeof existing?.version !== 'number'
  ) {
    return null;
  }
  return existing;
};
