import { api } from '@/lib/api';

export type CorrectionLocale = 'ru' | 'kk' | 'en';

/** Untrusted candidate, not an executable patch; the existing source owner rechecks it. */
export function buildCorrectionHandoffInstruction(instruction: string, candidate: string, locale: CorrectionLocale): string {
  if (!instruction.trim() || !candidate.trim()) throw new Error('Invalid correction handoff');
  const prefix = {
    ru: 'Проверь по исходным документам следующий НЕПРОВЕРЕННЫЙ вариант из диалога и подготовь предпросмотр правки сохранённого урока. Не принимай этот вариант за источник или выполненное изменение. Сохрани существенные факты, ограничения и неразрешённые противоречия источника. Новый предпросмотр может отличаться от варианта. Поручение пользователя:',
    kk: 'Диалогтағы келесі ТЕКСЕРІЛМЕГЕН нұсқаны бастапқы құжаттармен тексеріп, сақталған сабақты түзетудің алдын ала қарауын дайында. Бұл нұсқаны дереккөз не орындалған өзгеріс деп қабылдама. Дереккөздің маңызды фактілерін, шектеулерін және шешілмеген қайшылықтарын сақта. Жаңа ұсыныс нұсқадан өзгеше болуы мүмкін. Пайдаланушы тапсырмасы:',
    en: 'Check the following UNVERIFIED dialogue candidate against the original documents and prepare a correction preview of the saved lesson. Do not treat this candidate as a source or an executed change. Preserve the source facts, constraints and unresolved conflicts. The new preview may differ from the candidate. User instruction:',
  }[locale];
  if (!prefix) throw new Error('Invalid correction handoff');
  const value = `${prefix}\n${instruction}\n\n---\n${candidate}\n---`;
  if (Array.from(value).length > 4000) throw new Error('Correction handoff too large');
  return value;
}
export type LessonCorrectionRequest = {
  request_key: string;
  lesson_id: string;
  instruction: string;
  locale: CorrectionLocale;
};

export type CorrectionCitation = { document_id: string; locator: string; evidence_hash: string };
export type CorrectionProvenance = { provider: string; model_id: string; prompt_version: string; generator_version: string };
export type CorrectionProposal = { content: string; citations: CorrectionCitation[]; provenance: CorrectionProvenance; quality_policy: string };
export type LessonCorrectionPreview = {
  plan_id: string;
  lesson_id: string;
  revision: number;
  expires_at: string;
  state: 'pending' | 'ready' | 'failed';
  fingerprint: string | null;
  before_content: string | null;
  proposal: CorrectionProposal | null;
  error_code: string | null;
};
export type CorrectionApplicationReceipt = {
  plan_id: string;
  lesson_id: string;
  course_id: string;
  revision: number;
  fingerprint: string;
  before_sha256: string;
  after_sha256: string;
  applied_at: string;
  state: 'applied';
  source_review: 'needs_review';
  quiz_review: 'needs_review';
};
export type LessonCorrectionApplication = CorrectionApplicationReceipt;
export type LessonCorrectionSeal = Pick<LessonCorrectionPreview, 'plan_id' | 'revision' | 'fingerprint'>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/;
const CODE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$/;
const uuid = (value: unknown): value is string => typeof value === 'string' && UUID.test(value);
const sha256 = (value: unknown): value is string => typeof value === 'string' && SHA256.test(value);
const points = (value: unknown, maximum: number): value is string => typeof value === 'string' && Array.from(value).length <= maximum;
const nonBlank = (value: unknown, maximum: number): value is string => typeof value === 'string' && value.trim().length > 0 && points(value, maximum);
const code = (value: unknown): value is string => typeof value === 'string' && CODE.test(value);
const revision = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 1;
const awareDate = (value: unknown): value is string => typeof value === 'string'
  && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  && !Number.isNaN(Date.parse(value));
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

function parseCitation(value: unknown): CorrectionCitation {
  if (!object(value) || !uuid(value.document_id) || !nonBlank(value.locator, 120) || !sha256(value.evidence_hash)) throw new Error('Invalid correction citation');
  return { document_id: value.document_id, locator: value.locator, evidence_hash: value.evidence_hash };
}

function parseProvenance(value: unknown): CorrectionProvenance {
  if (!object(value) || !code(value.provider) || !code(value.model_id) || !code(value.prompt_version) || !code(value.generator_version)) throw new Error('Invalid correction provenance');
  return { provider: value.provider, model_id: value.model_id, prompt_version: value.prompt_version, generator_version: value.generator_version };
}

function parseProposal(value: unknown): CorrectionProposal {
  if (!object(value) || !nonBlank(value.content, 64000) || !Array.isArray(value.citations) || value.citations.length < 1 || value.citations.length > 64 || !value.citations.every((citation) => {
    try { parseCitation(citation); return true; } catch { return false; }
  }) || !object(value.provenance) || !nonBlank(value.quality_policy, Number.MAX_SAFE_INTEGER)) throw new Error('Invalid correction proposal');
  return {
    content: value.content,
    citations: value.citations.map(parseCitation),
    provenance: parseProvenance(value.provenance),
    quality_policy: value.quality_policy,
  };
}

export function parseLessonCorrectionPreview(value: unknown): LessonCorrectionPreview {
  if (!object(value) || !uuid(value.plan_id) || !uuid(value.lesson_id) || !revision(value.revision) || !awareDate(value.expires_at)
    || (typeof value.state !== 'string') || !['pending', 'ready', 'failed'].includes(value.state)) throw new Error('Invalid correction preview');
  const state = value.state as LessonCorrectionPreview['state'];
  if (state === 'ready') {
    if (!sha256(value.fingerprint) || !nonBlank(value.before_content, 64000) || !object(value.proposal) || value.error_code !== null && value.error_code !== undefined) throw new Error('Invalid ready correction preview');
    return { plan_id: value.plan_id, lesson_id: value.lesson_id, revision: value.revision, expires_at: value.expires_at, state, fingerprint: value.fingerprint, before_content: value.before_content, proposal: parseProposal(value.proposal), error_code: null };
  }
  if (value.fingerprint !== null && value.fingerprint !== undefined || value.before_content !== null && value.before_content !== undefined || value.proposal !== null && value.proposal !== undefined) throw new Error('Invalid non-ready correction preview');
  if (state === 'failed') {
    if (!nonBlank(value.error_code, Number.MAX_SAFE_INTEGER) || typeof value.error_code !== 'string') throw new Error('Invalid correction preview error');
    return { plan_id: value.plan_id, lesson_id: value.lesson_id, revision: value.revision, expires_at: value.expires_at, state, fingerprint: null, before_content: null, proposal: null, error_code: value.error_code };
  }
  if (value.error_code !== null && value.error_code !== undefined) throw new Error('Invalid correction preview error');
  return { plan_id: value.plan_id, lesson_id: value.lesson_id, revision: value.revision, expires_at: value.expires_at, state, fingerprint: null, before_content: null, proposal: null, error_code: null };
}

export function parseLessonCorrectionApplication(value: unknown): CorrectionApplicationReceipt {
  if (!object(value) || !uuid(value.plan_id) || !uuid(value.lesson_id) || !uuid(value.course_id) || !revision(value.revision)
    || !sha256(value.fingerprint) || !sha256(value.before_sha256) || !sha256(value.after_sha256) || !awareDate(value.applied_at)
    || value.state !== 'applied' || value.source_review !== 'needs_review' || value.quiz_review !== 'needs_review') throw new Error('Invalid correction application receipt');
  return { plan_id: value.plan_id, lesson_id: value.lesson_id, course_id: value.course_id, revision: value.revision, fingerprint: value.fingerprint, before_sha256: value.before_sha256, after_sha256: value.after_sha256, applied_at: value.applied_at, state: 'applied', source_review: 'needs_review', quiz_review: 'needs_review' };
}

function validateRequest(request: LessonCorrectionRequest): void {
  if (!object(request) || !uuid(request.request_key) || !uuid(request.lesson_id) || !nonBlank(request.instruction, 4000) || !['ru', 'kk', 'en'].includes(request.locale)) throw new Error('Invalid lesson correction request');
}

export async function createLessonCorrection(request: LessonCorrectionRequest, signal?: AbortSignal): Promise<LessonCorrectionPreview> {
  validateRequest(request);
  const response = await api.post('/v1/methodologist-workbench/lesson-correction-previews', request, signal ? { signal } : undefined);
  const parsed = parseLessonCorrectionPreview(response.data);
  if (parsed.lesson_id !== request.lesson_id) throw new Error('Correction lesson identity mismatch');
  return parsed;
}

export async function loadLessonCorrection(planId: string, signal?: AbortSignal): Promise<LessonCorrectionPreview> {
  if (!uuid(planId)) throw new Error('Invalid correction plan id');
  const response = await api.get(`/v1/methodologist-workbench/lesson-correction-previews/${encodeURIComponent(planId)}`, signal ? { signal } : undefined);
  const parsed = parseLessonCorrectionPreview(response.data);
  if (parsed.plan_id !== planId) throw new Error('Correction plan identity mismatch');
  return parsed;
}

export async function applyLessonCorrection(seal: LessonCorrectionSeal, signal?: AbortSignal): Promise<CorrectionApplicationReceipt> {
  if (!uuid(seal.plan_id) || !revision(seal.revision) || !sha256(seal.fingerprint)) throw new Error('Invalid correction application seal');
  const body = { plan_id: seal.plan_id, revision: seal.revision, fingerprint: seal.fingerprint };
  const response = await api.post(`/v1/methodologist-workbench/lesson-correction-previews/${encodeURIComponent(seal.plan_id)}/apply`, body, signal ? { signal } : undefined);
  const parsed = parseLessonCorrectionApplication(response.data);
  if (parsed.plan_id !== seal.plan_id || parsed.revision !== seal.revision || parsed.fingerprint !== seal.fingerprint) throw new Error('Correction application seal mismatch');
  return parsed;
}

export async function loadLessonCorrectionApplication(planId: string, signal?: AbortSignal): Promise<CorrectionApplicationReceipt | null> {
  if (!uuid(planId)) throw new Error('Invalid correction plan id');
  try {
    const response = await api.get(`/v1/methodologist-workbench/lesson-correction-previews/${encodeURIComponent(planId)}/application`, signal ? { signal } : undefined);
    const parsed = parseLessonCorrectionApplication(response.data);
    if (parsed.plan_id !== planId) throw new Error('Correction plan identity mismatch');
    return parsed;
  } catch (error) {
    const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
    if (status === 404) return null;
    throw error;
  }
}

/** Current document bytes only: citation evidence_hash hashes a fragment, not this file. */
export async function loadCorrectionSourceFile(documentId: string, signal?: AbortSignal): Promise<{ blob: Blob; filename: string; title: string }> {
  if (!uuid(documentId)) throw new Error('Invalid source file');
  const checkAbort = () => { if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError'); };
  checkAbort();
  const response = await api.get(`/v1/documents/${encodeURIComponent(documentId)}`, { signal });
  checkAbort();
  const metadata: unknown = response.data;
  if (!object(metadata) || metadata.id !== documentId || !nonBlank(metadata.filename, 1024)
    || !nonBlank(metadata.title, 1024) || !nonBlank(metadata.content_type, 255)
    || typeof metadata.size !== 'number' || !Number.isSafeInteger(metadata.size) || metadata.size <= 0) throw new Error('Invalid source file');
  const filename = metadata.filename.split(/[\\/]/).pop()!
    .replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '')
    .replace(/[:*?"<>|]/g, '_').trim();
  if (!filename || filename === '.' || filename === '..') throw new Error('Invalid source file');
  const bytes = await api.get(`/v1/documents/${encodeURIComponent(documentId)}/download`, { signal, responseType: 'blob' });
  checkAbort();
  const blob: unknown = bytes.data;
  const mime = (value: string) => value.split(';')[0].trim().toLowerCase();
  if (!(blob instanceof Blob) || blob.size <= 0 || blob.size !== metadata.size || mime(blob.type) !== mime(metadata.content_type)) throw new Error('Invalid source file');
  return { blob, filename, title: metadata.title };
}
