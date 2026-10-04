import { api } from '@/lib/api';

export type Choice = { id: string; label: string };
export type AssignmentInput = {
  instruction: string;
  timezone_name: string;
  notify: boolean;
  include_descendants: boolean;
  course_id?: string;
  department_id?: string;
  candidate?: AssignmentCandidate;
};
export type AssignmentCandidate = {
  course_query: string;
  department_query: string;
  due_date: string;
  due_time: string;
  notify: boolean;
  include_descendants: boolean;
};
export type AssignmentInterpretation = { state: 'interpreted'; candidate: AssignmentCandidate } | ClarificationResponse;
export type AssignmentRecipient = {
  user_id: string;
  label: string;
  already_assigned: boolean;
  access_warning: boolean;
};
export type ClarificationResponse = {
  state: 'clarification_needed';
  code: string;
  course_choices: Choice[];
  department_choices: Choice[];
};
export type PreviewReady = {
  state: 'preview_ready';
  plan_id: string;
  revision: number;
  fingerprint: string;
  expires_at: string;
  course_id: string;
  course_title: string;
  release_id: string;
  department_id: string;
  department_name: string;
  timezone_name: string;
  due_at: string;
  notify: boolean;
  include_descendants: boolean;
  recipients: AssignmentRecipient[];
  new_count: number;
  skipped_count: number;
};
export type AssignmentPreview = ClarificationResponse | PreviewReady;
export type AssignmentReceipt = {
  state: 'succeeded';
  plan_id: string;
  created: { user_id: string; enrollment_id: string; notification_id: string | null }[];
  skipped: string[];
  notification_state: 'queued' | 'not_requested';
};

const isString = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const isUuid = (value: unknown): value is string => typeof value === 'string' && UUID.test(value);
const isAwareIso = (value: unknown): value is string => typeof value === 'string' && /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
const isFingerprint = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const isChoice = (value: unknown): value is Choice => Boolean(value && typeof value === 'object' && isUuid((value as Choice).id) && isString((value as Choice).label));
const isRecipient = (value: unknown): value is AssignmentRecipient => {
  if (!value || typeof value !== 'object') return false;
  const item = value as AssignmentRecipient;
  return isUuid(item.user_id) && isString(item.label) && typeof item.already_assigned === 'boolean' && typeof item.access_warning === 'boolean';
};
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const isBoundedText = (value: unknown): value is string => typeof value === 'string' && value.trim().length >= 1 && value.length <= 300;
const isCalendarDate = (value: string): boolean => {
  const [year, month, day] = value.split('-').map(Number);
  if (!year || !month || !day || month < 1 || month > 12 || day < 1) return false;
  return new Date(Date.UTC(year, month - 1, day)).getUTCFullYear() === year
    && new Date(Date.UTC(year, month - 1, day)).getUTCMonth() === month - 1
    && new Date(Date.UTC(year, month - 1, day)).getUTCDate() === day;
};
const isClockTime = (value: string): boolean => {
  const [hour, minute, second] = value.split(':').map(Number);
  return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59 && second >= 0 && second <= 59;
};
export const isAssignmentCandidate = (value: unknown): value is AssignmentCandidate => {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).sort().join(',') !== 'course_query,department_query,due_date,due_time,include_descendants,notify') return false;
  return isBoundedText(candidate.course_query) && isBoundedText(candidate.department_query)
    && typeof candidate.due_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(candidate.due_date) && isCalendarDate(candidate.due_date)
    && typeof candidate.due_time === 'string' && /^\d{2}:\d{2}:\d{2}$/.test(candidate.due_time) && isClockTime(candidate.due_time)
    && typeof candidate.notify === 'boolean' && typeof candidate.include_descendants === 'boolean';
};
const isCandidate = isAssignmentCandidate;

function parsePreview(value: unknown): AssignmentPreview {
  if (!value || typeof value !== 'object') throw new Error('Invalid assignment preview response');
  const data = value as Partial<AssignmentPreview>;
  if (data.state === 'clarification_needed' && isString(data.code)
    && Array.isArray(data.course_choices) && data.course_choices.length <= 20 && data.course_choices.every(isChoice)
    && Array.isArray(data.department_choices) && data.department_choices.length <= 20 && data.department_choices.every(isChoice)) {
    if (new Set([...data.course_choices, ...data.department_choices].map((choice) => choice.id)).size !== data.course_choices.length + data.department_choices.length) throw new Error('Invalid clarification identities');
    return { state: 'clarification_needed', code: data.code, course_choices: data.course_choices, department_choices: data.department_choices };
  }
  if (data.state === 'preview_ready' && isUuid(data.plan_id) && Number.isInteger(data.revision) && (data.revision as number) >= 1
    && isFingerprint(data.fingerprint) && isAwareIso(data.expires_at) && isUuid(data.course_id)
    && isString(data.course_title) && isUuid(data.release_id) && isUuid(data.department_id)
    && isString(data.department_name) && isString(data.timezone_name) && isAwareIso(data.due_at)
    && typeof data.notify === 'boolean' && typeof data.include_descendants === 'boolean'
    && Array.isArray(data.recipients) && data.recipients.length >= 1 && data.recipients.length <= 5000 && data.recipients.every(isRecipient)
    && isCount(data.new_count) && isCount(data.skipped_count)
    && data.new_count + data.skipped_count === data.recipients.length) {
    const ids = new Set(data.recipients.map((recipient) => recipient.user_id));
    if (ids.size !== data.recipients.length) throw new Error('Invalid recipient identities');
    const newCount = data.recipients.filter((recipient) => !recipient.already_assigned).length;
    if (data.new_count !== newCount || data.skipped_count !== data.recipients.length - newCount) throw new Error('Invalid recipient counts');
    return data as PreviewReady;
  }
  throw new Error('Invalid assignment preview response');
}

function parseReceipt(value: unknown, planId: string): AssignmentReceipt {
  if (!value || typeof value !== 'object') throw new Error('Invalid assignment receipt response');
  const data = value as Partial<AssignmentReceipt>;
  if (data.state !== 'succeeded' || data.plan_id !== planId || !Array.isArray(data.created) || data.created.length > 5000
    || !data.created.every((item) => Boolean(item && isUuid(item.user_id) && isUuid(item.enrollment_id)
      && (item.notification_id === null || isUuid(item.notification_id))))
    || !Array.isArray(data.skipped) || data.skipped.length > 5000 || !data.skipped.every(isUuid)
    || (data.notification_state !== 'queued' && data.notification_state !== 'not_requested')) {
    throw new Error('Invalid assignment receipt response');
  }
  const createdUsers = data.created.map((item) => item.user_id);
  const createdEnrollments = data.created.map((item) => item.enrollment_id);
  const skipped = data.skipped as string[];
  if (new Set(createdUsers).size !== createdUsers.length || new Set(createdEnrollments).size !== createdEnrollments.length
    || new Set(skipped).size !== skipped.length || createdUsers.some((id) => skipped.includes(id))) throw new Error('Invalid receipt identities');
  return data as AssignmentReceipt;
}

export async function requestAssignmentPreview(input: AssignmentInput, signal?: AbortSignal): Promise<AssignmentPreview> {
  if (input.instruction.trim().length < 1 || input.instruction.length > 4000
    || !isString(input.timezone_name) || typeof input.notify !== 'boolean'
    || typeof input.include_descendants !== 'boolean'
    || (input.course_id !== undefined && !isUuid(input.course_id))
    || (input.department_id !== undefined && !isUuid(input.department_id))
    || (input.candidate !== undefined && !isCandidate(input.candidate))) throw new Error('Invalid assignment input');
  const response = signal ? await api.post('/v1/methodologist-workbench/assignment-preview', input, { signal }) : await api.post('/v1/methodologist-workbench/assignment-preview', input);
  return parsePreview(response.data);
}

export async function interpretAssignment(instruction: string, timezone_name: string, notify: boolean, include_descendants: boolean, previous_plan_id?: string, signal?: AbortSignal): Promise<AssignmentInterpretation> {
  if (instruction.trim().length < 1 || instruction.length > 4000 || !isString(timezone_name)
    || typeof notify !== 'boolean' || typeof include_descendants !== 'boolean'
    || (previous_plan_id !== undefined && !isUuid(previous_plan_id))) throw new Error('Invalid assignment interpretation input');
  const response = await api.post('/v1/methodologist-workbench/interpret-assignment', {
    instruction, timezone_name, notify, include_descendants, ...(previous_plan_id ? { previous_plan_id } : {}),
  }, signal ? { signal } : undefined);
  if (!response.data || typeof response.data !== 'object') throw new Error('Invalid assignment interpretation response');
  const data = response.data as Record<string, unknown>;
  if (data.state === 'interpreted' && Object.keys(data).sort().join(',') === 'candidate,state' && isCandidate(data.candidate)) return { state: 'interpreted', candidate: data.candidate };
  const clarification = parsePreview(data);
  if (clarification.state !== 'clarification_needed') throw new Error('Invalid assignment interpretation response');
  return clarification;
}

export async function loadAssignmentPlan(planId: string, signal?: AbortSignal): Promise<AssignmentPreview | AssignmentReceipt> {
  if (!isUuid(planId)) throw new Error('Invalid plan id');
  const response = await api.get(`/v1/methodologist-workbench/plans/${encodeURIComponent(planId)}`, signal ? { signal } : undefined);
  if (response.data?.state === 'succeeded') return parseReceipt(response.data, planId);
  const parsed = parsePreview(response.data);
  if (parsed.state === 'preview_ready' && parsed.plan_id !== planId) throw new Error('Plan identity mismatch');
  return parsed;
}

export async function confirmAssignmentPlan(plan: PreviewReady): Promise<AssignmentReceipt> {
  const response = await api.post(`/v1/methodologist-workbench/plans/${encodeURIComponent(plan.plan_id)}/confirm`, {
    plan_id: plan.plan_id,
    revision: plan.revision,
    fingerprint: plan.fingerprint,
  });
  return parseReceipt(response.data, plan.plan_id);
}
