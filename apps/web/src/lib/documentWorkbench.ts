import { api } from '@/lib/api';
import type { AIGenerationJob } from '@/lib/aiGenerationJobs';

export type CourseFormat = 'automatic' | 'brief' | 'standard' | 'detailed';
export type DocumentLanguage = 'ru' | 'kk' | 'en';
export type SourceStrategy = 'single_topic' | 'intentional_combination';

export type AIGenerateRequest = {
  documents: string[];
  target_audience: string;
  course_intent: string;
  course_format: CourseFormat;
  num_modules?: number | null;
  language: DocumentLanguage;
  tone?: string;
  source_strategy: SourceStrategy;
  combination_goal: string;
  reuse_reason?: 'different_audience' | 'different_language' | 'different_depth' | 'updated_revision' | 'recurring_training' | 'other' | null;
  language_confirmed: boolean;
};

export type DocumentPreviewRequest = { instruction: string; generation: AIGenerateRequest };
export type DocumentSource = { document_id: string; title: string; version: number; content_sha256: string; index_revision: number };
export type DocumentPreview = {
  state: 'preview_ready'; plan_id: string; revision: number; fingerprint: string; expires_at: string;
  instruction: string; generation: AIGenerateRequest; sources: DocumentSource[];
};
export type DocumentExecution = { state: 'submitted'; plan_id: string; job: AIGenerationJob };
export type DocumentPlan = DocumentPreview | DocumentExecution;
export type DocumentCandidate = Pick<AIGenerateRequest, 'target_audience' | 'course_intent' | 'course_format' | 'language' | 'source_strategy' | 'combination_goal'>;
export type DocumentInterpretation = { state: 'interpreted'; candidate: DocumentCandidate } | { state: 'clarification_needed'; code: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/i;
const uuid = (v: unknown): v is string => typeof v === 'string' && UUID.test(v);
const text = (v: unknown, max = 4000): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
const bounded = (v: unknown, max: number): v is string => typeof v === 'string' && v.length <= max;
const date = (v: unknown): v is string => typeof v === 'string' && !Number.isNaN(Date.parse(v));

export function isAIGenerateRequest(value: unknown): value is AIGenerateRequest {
  if (!value || typeof value !== 'object') return false;
  const v = value as Partial<AIGenerateRequest>;
  return Array.isArray(v.documents) && v.documents.length >= 1 && v.documents.length <= 5 && new Set(v.documents).size === v.documents.length && v.documents.every(uuid)
    && bounded(v.target_audience, 2000) && text(v.course_intent, 2000) && ['automatic', 'brief', 'standard', 'detailed'].includes(v.course_format ?? '')
    && (v.num_modules == null || (Number.isInteger(v.num_modules) && v.num_modules >= 1 && v.num_modules <= 10))
    && ['ru', 'kk', 'en'].includes(v.language ?? '') && (v.tone === undefined || text(v.tone, 100))
    && ['single_topic', 'intentional_combination'].includes(v.source_strategy ?? '') && bounded(v.combination_goal, 2000)
    && typeof v.language_confirmed === 'boolean'
    && (v.source_strategy !== 'intentional_combination' || v.combination_goal.trim().length >= 20);
}

function parseJob(value: unknown): AIGenerationJob {
  if (!value || typeof value !== 'object') throw new Error('Invalid document plan job');
  const v = value as Partial<AIGenerationJob>;
  if (!text(v.id, 100) || !text(v.status, 50) || !text(v.job_type, 50) || (v.course_id !== null && v.course_id !== undefined && !uuid(v.course_id))) throw new Error('Invalid document plan job');
  return value as AIGenerationJob;
}

function parseSource(value: unknown): DocumentSource {
  if (!value || typeof value !== 'object') throw new Error('Invalid document source');
  const v = value as Partial<DocumentSource>;
  if (!uuid(v.document_id) || !text(v.title, 500) || !Number.isInteger(v.version) || (v.version ?? 0) < 1 || !SHA256.test(v.content_sha256 ?? '') || !Number.isInteger(v.index_revision) || (v.index_revision ?? 0) < 1) throw new Error('Invalid document source');
  return value as DocumentSource;
}

export function parseDocumentPlan(value: unknown): DocumentPlan {
  if (!value || typeof value !== 'object') throw new Error('Invalid document plan');
  const v = value as Partial<DocumentPlan>;
  if (!uuid(v.plan_id)) throw new Error('Invalid document plan identity');
  if (v.state === 'submitted') return { state: 'submitted', plan_id: v.plan_id, job: parseJob(v.job) };
  if (v.state !== 'preview_ready' || !Number.isInteger(v.revision) || (v.revision ?? 0) < 1 || !SHA256.test(v.fingerprint ?? '') || !date(v.expires_at) || !text(v.instruction) || !isAIGenerateRequest(v.generation) || !Array.isArray(v.sources) || v.sources.length < 1 || v.sources.length > 5) throw new Error('Invalid document preview');
  return { ...value, sources: v.sources.map(parseSource) } as DocumentPreview;
}

export async function previewDocumentPlan(request: DocumentPreviewRequest, signal?: AbortSignal): Promise<DocumentPreview> {
  if (!text(request.instruction) || !isAIGenerateRequest(request.generation)) throw new Error('Invalid document preview input');
  const response = await api.post('/v1/methodologist-workbench/document-preview', request, signal ? { signal } : undefined);
  const parsed = parseDocumentPlan(response.data);
  if (parsed.state !== 'preview_ready') throw new Error('Unexpected submitted document plan');
  return parsed;
}

export async function loadDocumentPlan(planId: string, signal?: AbortSignal): Promise<DocumentPlan> {
  if (!uuid(planId)) throw new Error('Invalid document plan id');
  const response = await api.get(`/v1/methodologist-workbench/document-plans/${encodeURIComponent(planId)}`, signal ? { signal } : undefined);
  const parsed = parseDocumentPlan(response.data);
  if (parsed.plan_id !== planId) throw new Error('Document plan identity mismatch');
  return parsed;
}

export async function confirmDocumentPlan(preview: Pick<DocumentPreview, 'plan_id' | 'revision' | 'fingerprint'>): Promise<DocumentExecution> {
  const response = await api.post(`/v1/methodologist-workbench/document-plans/${encodeURIComponent(preview.plan_id)}/confirm`, {
    plan_id: preview.plan_id, revision: preview.revision, fingerprint: preview.fingerprint,
  });
  const parsed = parseDocumentPlan(response.data);
  if (parsed.state !== 'submitted' || parsed.plan_id !== preview.plan_id) throw new Error('Unexpected document confirmation response');
  return parsed;
}

export async function interpretDocument(instruction: string, language: DocumentLanguage, signal?: AbortSignal): Promise<DocumentInterpretation> {
  if (!text(instruction)) throw new Error('Invalid document interpretation input');
  const response = await api.post('/v1/methodologist-workbench/interpret-document', { instruction, language }, signal ? { signal } : undefined);
  const value = response.data as { state?: unknown; code?: unknown; candidate?: Partial<DocumentCandidate> };
  if (value.state === 'clarification_needed' && text(value.code, 100)) return { state: 'clarification_needed', code: value.code };
  const candidate = value.candidate as Partial<DocumentCandidate> | undefined;
  if (value.state === 'interpreted' && candidate && bounded(candidate.target_audience, 2000) && bounded(candidate.course_intent, 2000) && ['automatic', 'brief', 'standard', 'detailed'].includes(candidate.course_format ?? '') && ['ru', 'kk', 'en'].includes(candidate.language ?? '') && ['single_topic', 'intentional_combination'].includes(candidate.source_strategy ?? '') && bounded(candidate.combination_goal, 2000)) return { state: 'interpreted', candidate: candidate as DocumentCandidate };
  throw new Error('Invalid document interpretation response');
}
