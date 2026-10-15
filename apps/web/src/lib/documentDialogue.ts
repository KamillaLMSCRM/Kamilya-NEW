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
  response: DocumentInterpretation | null; error_code: string | null; created_at: string;
};
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
    return { ...e, response: parseInterpretation(e.response, v.language) };
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
export async function previewDocumentDialogue(id: string, expected_revision: number, signal?: AbortSignal): Promise<DocumentPreview> {
  if (!UUID.test(id) || !Number.isInteger(expected_revision) || expected_revision < 1) throw new Error('Invalid document dialogue revision');
  const response = await api.post(`${base}/${encodeURIComponent(id)}/preview`, { expected_revision }, signal ? { signal } : undefined);
  const plan = (await import('@/lib/documentWorkbench')).parseDocumentPlan(response.data);
  if (plan.state !== 'preview_ready') throw new Error('Unexpected submitted document dialogue plan');
  return plan;
}
