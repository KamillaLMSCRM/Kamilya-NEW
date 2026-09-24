import { api } from '@/lib/api';
import type {
  CreateLearningAction,
  LearningAction,
  LearningActionCenterPayload,
  LearningActionResolution,
} from './types';

const BASE = '/v1/admin/learning-actions';

export async function getLearningActionCenter(courseId?: string): Promise<LearningActionCenterPayload> {
  const params = new URLSearchParams();
  if (courseId) params.set('course_id', courseId);
  const response = await api.get<LearningActionCenterPayload>(`${BASE}${params.size ? `?${params}` : ''}`);
  const data = response.data as Partial<LearningActionCenterPayload>;
  return {
    summary: {
      training_issue_count: data.summary?.training_issue_count ?? 0,
      training_issue_counts: data.summary?.training_issue_counts ?? {},
      training_items_truncated: data.summary?.training_items_truncated ?? false,
      weak_question_count: data.summary?.weak_question_count ?? 0,
      action_count: data.summary?.action_count ?? 0,
      actions_truncated: data.summary?.actions_truncated ?? false,
      open_action_count: data.summary?.open_action_count ?? 0,
      overdue_action_count: data.summary?.overdue_action_count ?? 0,
    },
    training_items: Array.isArray(data.training_items)
      ? data.training_items.map((item) => ({
        ...item,
        active_action_types: Array.isArray(item.active_action_types) ? item.active_action_types : [],
      }))
      : [],
    weak_questions: Array.isArray(data.weak_questions)
      ? data.weak_questions.map((item) => ({
        ...item,
        active_action_types: Array.isArray(item.active_action_types) ? item.active_action_types : [],
      }))
      : [],
    actions: Array.isArray(data.actions) ? data.actions : [],
  };
}

export async function createLearningAction(payload: CreateLearningAction): Promise<LearningAction> {
  const response = await api.post<LearningAction>(BASE, payload);
  return response.data;
}

export async function closeLearningAction(
  id: string,
  resolution: LearningActionResolution,
  note: string | null,
): Promise<LearningAction> {
  const response = await api.post<LearningAction>(`${BASE}/${id}/close`, {
    resolution,
    note,
  });
  return response.data;
}
