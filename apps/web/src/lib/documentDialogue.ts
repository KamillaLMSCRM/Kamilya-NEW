import { api } from '@/lib/api';
import type { DocumentCandidate, DocumentInterpretation, DocumentLanguage, DocumentPreview } from '@/lib/documentWorkbench';

export type DocumentDialogueDraft = {
  instruction: string;
  candidate: DocumentCandidate;
  language_confirmed: boolean;
  reuse_reason: 'different_audience' | 'different_language' | 'different_depth' | 'updated_revision' | 'recurring_training' | 'other' | null;
};
export type DocumentDialogueExchange = {
  id: string; instruction: string; state: 'pending' | 'completed' | 'failed';
  response: DocumentInterpretation | DocumentContentAnswer | null; error_code: string | null; created_at: string;
};
export type DocumentContentCitation = {
  number: number; document_id: string; title: string; version: number; content_sha256: string;
  index_revision: number; chunk_id: string; quote: string;
};
export type DocumentContentAnswer = {
  state: 'answered'; status: 'supported' | 'not_found' | 'conflict'; answer: string; citations: DocumentContentCitation[];
};
export type DocumentContentSourceExcerpt = { citation: DocumentContentCitation; excerpt: string };
export type DocumentContentSourceFile = { blob: Blob; filename: string };
export type DocumentDialogueTask = {
  id: string; revision: number; language: DocumentLanguage;
  sources: Array<{ document_id: string; title: string; version: number; content_sha256: string; index_revision: number }>;
  draft: DocumentDialogueDraft; plan_id: string | null; source_stale: boolean;
  pending_request_id: string | null; interrupted_request_id: string | null;
  exchanges: DocumentDialogueExchange[]; created_at: string; updated_at: string;
};
export type DocumentDialogueList = { tasks: Array<{ id: string; title: string; updated_at: string; plan_id: string | null }>; has_more: boolean; next_before: string | null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[0-9a-f]{64}$/i;
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every((key) => keys.includes(key)) && keys.every((key) => key in value);
const stableJson = (value: unknown): string => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right))) : item);
const isText = (v: unknown, max = 4000, empty = false): v is string => typeof v === 'string' && v.length <= max && (empty || v.length > 0);
const validDate = (v: unknown): v is string => typeof v === 'string' && !Number.isNaN(Date.parse(v));
const validCandidate = (v: any, language: unknown): v is DocumentCandidate => Boolean(v && typeof v === 'object'
  && isText(v.target_audience, 2000, true) && isText(v.course_intent, 2000, true)
  && ['automatic', 'brief', 'standard', 'detailed'].includes(v.course_format)
  && ['ru', 'kk', 'en'].includes(v.language) && v.language === language
  && ['single_topic', 'intentional_combination'].includes(v.source_strategy)
  && isText(v.combination_goal, 2000, true));
const reuseReasons = [null, 'different_audience', 'different_language', 'different_depth', 'updated_revision', 'recurring_training', 'other'];
export function parseDocumentDialogueDraft(v: unknown, language: DocumentLanguage): DocumentDialogueDraft {
  const draft = v as any;
  if (!draft || !isText(draft.instruction, 4000, true) || !validCandidate(draft.candidate, language)
    || typeof draft.language_confirmed !== 'boolean' || !reuseReasons.includes(draft.reuse_reason)) throw new Error('Invalid document dialogue draft');
  return draft as DocumentDialogueDraft;
}
function parseInterpretation(v: any, language: DocumentLanguage): DocumentInterpretation | null {
  if (v === null) return null;
  if (v?.state === 'clarification_needed' && isText(v.code, 100)) return v as DocumentInterpretation;
  if (v?.state === 'interpreted' && validCandidate(v.candidate, language)) return v as DocumentInterpretation;
  throw new Error('Invalid document dialogue response');
}
function parseCitation(v: any, sources: DocumentDialogueTask['sources']): DocumentContentCitation {
  if (!v || typeof v !== 'object' || !exactKeys(v, ['number', 'document_id', 'title', 'version', 'content_sha256', 'index_revision', 'chunk_id', 'quote'])
    || !Number.isInteger(v.number) || v.number < 1 || !UUID.test(v.document_id ?? '')
    || !isText(v.title, 500) || !Number.isInteger(v.version) || v.version < 1 || !SHA.test(v.content_sha256 ?? '')
    || !Number.isInteger(v.index_revision) || v.index_revision < 1 || !/^[0-9a-f]{64}$/.test(v.chunk_id ?? '')
    || !isText(v.quote, 1600)) throw new Error('Invalid document content citation');
  const source = sources.find((item) => item.document_id === v.document_id);
  if (!source || source.title !== v.title || source.version !== v.version || source.content_sha256 !== v.content_sha256
    || source.index_revision !== v.index_revision) throw new Error('Document content citation does not match task sources');
  return v as DocumentContentCitation;
}
function parseContentAnswer(v: any, sources: DocumentDialogueTask['sources']): DocumentContentAnswer {
  if (!v || typeof v !== 'object' || !exactKeys(v, ['state', 'status', 'answer', 'citations'])
    || v.state !== 'answered' || !['supported', 'not_found', 'conflict'].includes(v.status)
    || !isText(v.answer, 8000) || !Array.isArray(v.citations) || v.citations.length > 8) throw new Error('Invalid document content answer');
  const citations = v.citations.map((citation: unknown) => parseCitation(citation, sources));
  if (new Set(citations.map((citation: DocumentContentCitation) => citation.number)).size !== citations.length
    || (v.status === 'not_found' ? citations.length !== 0 : citations.length === 0)) throw new Error('Invalid document content citation set');
  return { ...v, citations } as DocumentContentAnswer;
}
function parseDialogueResponse(v: any, language: DocumentLanguage, sources: DocumentDialogueTask['sources']) {
  return v?.state === 'answered' ? parseContentAnswer(v, sources) : parseInterpretation(v, language);
}
export function parseDocumentDialogueTask(v: any): DocumentDialogueTask {
  if (!v || typeof v !== 'object' || !UUID.test(v.id ?? '') || !Number.isInteger(v.revision) || v.revision < 1
    || !['ru', 'kk', 'en'].includes(v.language) || !Array.isArray(v.sources) || v.sources.length < 1 || v.sources.length > 5
    || !Array.isArray(v.exchanges) || v.exchanges.length > 40 || (v.plan_id !== null && !UUID.test(v.plan_id))
    || typeof v.source_stale !== 'boolean' || (v.pending_request_id !== null && !UUID.test(v.pending_request_id))
    || (v.interrupted_request_id !== null && !UUID.test(v.interrupted_request_id)) || !validDate(v.created_at) || !validDate(v.updated_at)) throw new Error('Invalid document dialogue task');
  const sources = v.sources.map((s: any) => {
    if (!UUID.test(s?.document_id ?? '') || !isText(s.title, 500) || !Number.isInteger(s.version) || s.version < 1 || !SHA.test(s.content_sha256 ?? '') || !Number.isInteger(s.index_revision) || s.index_revision < 1) throw new Error('Invalid document dialogue source');
    return s;
  });
  if (new Set(sources.map((source: { document_id: string }) => source.document_id)).size !== sources.length) throw new Error('Duplicate document dialogue source');
  const exchanges = v.exchanges.map((e: any) => {
    if (!UUID.test(e?.id ?? '') || !isText(e.instruction, 4000) || !['pending', 'completed', 'failed'].includes(e.state)
      || (e.error_code !== null && !isText(e.error_code, 100)) || !validDate(e.created_at)) throw new Error('Invalid document dialogue exchange');
    return { ...e, response: parseDialogueResponse(e.response, v.language, sources) };
  });
  return { ...v, draft: parseDocumentDialogueDraft(v.draft, v.language), sources, exchanges } as DocumentDialogueTask;
}
export function parseDocumentDialogueList(v: any): DocumentDialogueList {
  if (!v || !Array.isArray(v.tasks) || v.tasks.length > 20 || typeof v.has_more !== 'boolean'
    || (v.next_before !== null && !UUID.test(v.next_before))) throw new Error('Invalid document dialogue list');
  const tasks = v.tasks.map((t: any) => {
    if (!UUID.test(t?.id ?? '') || !isText(t.title, 500) || !validDate(t.updated_at) || (t.plan_id !== null && !UUID.test(t.plan_id))) throw new Error('Invalid document dialogue list item');
    return t;
  });
  return { ...v, tasks } as DocumentDialogueList;
}
const base = '/v1/methodologist-workbench/document-dialogues';
export async function listDocumentDialogues(before?: string, signal?: AbortSignal): Promise<DocumentDialogueList> {
  if (before && !UUID.test(before)) throw new Error('Invalid document dialogue cursor');
  const response = await api.get(`${base}${before ? `?before=${encodeURIComponent(before)}` : ''}`, signal ? { signal } : undefined);
  return parseDocumentDialogueList(response.data);
}
export async function getDocumentDialogue(id: string, signal?: AbortSignal): Promise<DocumentDialogueTask> {
  if (!UUID.test(id)) throw new Error('Invalid document dialogue id');
  const response = await api.get(`${base}/${encodeURIComponent(id)}`, signal ? { signal } : undefined);
  const task = parseDocumentDialogueTask(response.data);
  if (task.id !== id) throw new Error('Document dialogue identity mismatch');
  return task;
}
export async function createDocumentDialogue(input: { task_id: string; document_ids: string[]; language: DocumentLanguage; draft: DocumentDialogueDraft }, signal?: AbortSignal): Promise<DocumentDialogueTask> {
  if (!UUID.test(input.task_id) || input.document_ids.length < 1 || input.document_ids.length > 5 || new Set(input.document_ids).size !== input.document_ids.length || !input.document_ids.every((id) => UUID.test(id))
    || !['ru', 'kk', 'en'].includes(input.language)) throw new Error('Invalid document dialogue input');
  const draft = parseDocumentDialogueDraft(input.draft, input.language);
  const response = await api.post(base, { ...input, draft }, signal ? { signal } : undefined);
  const task = parseDocumentDialogueTask(response.data);
  if (task.id !== input.task_id) throw new Error('Document dialogue identity mismatch');
  return task;
}
export async function saveDocumentDialogue(id: string, expected_revision: number, draft: DocumentDialogueDraft, language: DocumentLanguage, signal?: AbortSignal): Promise<DocumentDialogueTask> {
  if (!UUID.test(id) || !Number.isInteger(expected_revision) || expected_revision < 1) throw new Error('Invalid document dialogue revision');
  const validatedDraft = parseDocumentDialogueDraft(draft, language);
  const response = await api.patch(`${base}/${encodeURIComponent(id)}`, { expected_revision, draft: validatedDraft }, signal ? { signal } : undefined);
  const task = parseDocumentDialogueTask(response.data);
  if (task.id !== id) throw new Error('Document dialogue identity mismatch');
  return task;
}
export async function messageDocumentDialogue(id: string, request_id: string, expected_revision: number, instruction: string, signal?: AbortSignal): Promise<DocumentDialogueTask> {
  if (!UUID.test(id) || !UUID.test(request_id) || !Number.isInteger(expected_revision) || expected_revision < 1 || !isText(instruction.trim(), 4000)) throw new Error('Invalid document dialogue message');
  const response = await api.post(`${base}/${encodeURIComponent(id)}/messages`, { request_id, expected_revision, instruction: instruction.trim() }, signal ? { signal } : undefined);
  const task = parseDocumentDialogueTask(response.data);
  if (task.id !== id) throw new Error('Document dialogue identity mismatch');
  return task;
}
export async function messageDocumentContentDialogue(task: DocumentDialogueTask, request_id: string, instruction: string, signal?: AbortSignal): Promise<DocumentDialogueTask> {
  if (!UUID.test(task.id) || !UUID.test(request_id) || !Number.isInteger(task.revision) || task.revision < 1 || !isText(instruction.trim(), 4000)) throw new Error('Invalid document content message');
  if (task.plan_id) throw new Error('Document content questions require a task without a linked plan');
  const response = await api.post(`${base}/${encodeURIComponent(task.id)}/content-messages`, {
    request_id, expected_revision: task.revision, instruction: instruction.trim(),
  }, signal ? { signal } : undefined);
  const next = parseDocumentDialogueTask(response.data);
  if (next.id !== task.id) throw new Error('Document dialogue identity mismatch');
  if (stableJson(next.draft) !== stableJson(task.draft) || next.plan_id !== task.plan_id
    || stableJson(next.sources) !== stableJson(task.sources)) throw new Error('Content question changed preparation state');
  return next;
}
export async function getDocumentContentSourceExcerpt(task: DocumentDialogueTask, exchangeId: string, citation: DocumentContentCitation, signal?: AbortSignal): Promise<DocumentContentSourceExcerpt> {
  if (!UUID.test(task.id) || !UUID.test(exchangeId) || !Number.isInteger(citation.number) || citation.number < 1) throw new Error('Invalid document citation locator');
  if (task.source_stale) throw new Error('Document source changed');
  parseCitation(citation, task.sources);
  const response = await api.get(`${base}/${encodeURIComponent(task.id)}/sources/${encodeURIComponent(exchangeId)}/${citation.number}`, signal ? { signal } : undefined);
  const body = response.data as any;
  const returnedCitation = parseCitation(body?.citation, task.sources);
  if (!body || typeof body !== 'object' || !exactKeys(body, ['citation', 'excerpt'])
    || stableJson(returnedCitation) !== stableJson(citation) || !isText(body?.excerpt, 6000, true)) throw new Error('Invalid document source excerpt');
  return { citation: returnedCitation, excerpt: body.excerpt };
}
const safeFilename = (value: string | undefined, fallback: string): string => {
  let name = fallback;
  if (value) {
    const extended = value.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1];
    const quoted = value.match(/filename\s*=\s*"?([^";\r\n]+)"?/i)?.[1];
    const candidate = extended ?? quoted;
    if (candidate) {
      try { name = decodeURIComponent(candidate.trim()); } catch { name = candidate.trim(); }
    }
  }
  name = name.split(/[\\/]/).pop()!.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '').replace(/[:*?"<>|]/g, '_').trim();
  return name && name !== '.' && name !== '..' ? name : fallback;
};
export async function downloadDocumentContentSource(task: DocumentDialogueTask, exchangeId: string, citation: DocumentContentCitation, signal?: AbortSignal): Promise<DocumentContentSourceFile> {
  if (!UUID.test(task.id) || !UUID.test(exchangeId) || !Number.isInteger(citation.number) || citation.number < 1 || task.source_stale) throw new Error('Invalid document source download');
  parseCitation(citation, task.sources);
  const response = await api.get<Blob>(`${base}/${encodeURIComponent(task.id)}/sources/${encodeURIComponent(exchangeId)}/${citation.number}/download`, {
    ...(signal ? { signal } : {}), responseType: 'blob',
  });
  if (!(response.data instanceof Blob) || response.data.size <= 0) throw new Error('Invalid document source file');
  return { blob: response.data, filename: safeFilename(response.headers?.['content-disposition'], `${citation.title}.download`) };
}
export async function previewDocumentDialogue(id: string, expected_revision: number, signal?: AbortSignal): Promise<DocumentPreview> {
  if (!UUID.test(id) || !Number.isInteger(expected_revision) || expected_revision < 1) throw new Error('Invalid document dialogue revision');
  const response = await api.post(`${base}/${encodeURIComponent(id)}/preview`, { expected_revision }, signal ? { signal } : undefined);
  const plan = (await import('@/lib/documentWorkbench')).parseDocumentPlan(response.data);
  if (plan.state !== 'preview_ready') throw new Error('Unexpected submitted document dialogue plan');
  return plan;
}
