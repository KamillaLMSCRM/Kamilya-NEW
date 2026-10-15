import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/apiErrorMessage';

export interface GenerationModelRoute {
  id: string;
  provider: string;
  display_name: string;
  model: string;
  is_enabled: boolean;
  position: number | null;
  is_required: boolean;
  is_configured: boolean;
  activation_blocker?: string | null;
}

export type ChatGPTReadinessReason =
  | 'not_configured'
  | 'authorization_required'
  | 'unavailable'
  | 'protocol_mismatch'
  | 'ready';

export interface ChatGPTReadiness {
  ready: boolean;
  reason: ChatGPTReadinessReason;
  checked_at: string;
}

export interface GenerationModelRouting {
  revision: number;
  models: GenerationModelRoute[];
  updated_at: string;
}

/** Build an activation order from the server snapshot, never from an unsaved UI draft. */
export function buildChatGPTReserveOrder(routing: GenerationModelRouting, enabled: boolean): string[] {
  const order = routing.models
    .filter((model) => model.is_enabled)
    .sort((left, right) => (left.position ?? 999) - (right.position ?? 999))
    .map((model) => model.id)
    .filter((id) => id !== 'chatgpt_reserve');
  if (enabled) {
    const deepSeekIndex = order.indexOf('deepseek');
    order.splice(deepSeekIndex < 0 ? 0 : deepSeekIndex + 1, 0, 'chatgpt_reserve');
  }
  return order;
}

export class ModelRoutingRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly reason?: ChatGPTReadinessReason,
  ) {
    super(message);
  }
}

function errorDetail(error: unknown, fallback: string) {
  const response = (error as { response?: { data?: { detail?: unknown }; status?: number } } | null)?.response;
  const detail = response?.data?.detail;
  const rawReason = typeof detail === 'string'
    ? detail
    : typeof detail === 'object' && detail !== null && 'reason' in detail
      ? detail.reason : undefined;
  const reason = ['not_configured', 'authorization_required', 'unavailable', 'protocol_mismatch']
    .find((candidate) => rawReason === candidate) as ChatGPTReadinessReason | undefined;
  return {
    message: apiErrorMessage(error, fallback),
    status: response?.status ?? 0,
    reason,
  };
}

export async function getGenerationModelRouting(): Promise<GenerationModelRouting> {
  try {
    const response = await api.get<GenerationModelRouting>('/v1/admin/model-routing');
    return response.data;
  } catch (error) {
    const detail = errorDetail(error, 'Failed to load model routing');
    throw new ModelRoutingRequestError(detail.message, detail.status, detail.reason);
  }
}

export async function saveGenerationModelRouting(
  revision: number,
  orderedModelIds: string[],
): Promise<GenerationModelRouting> {
  try {
    const response = await api.put<GenerationModelRouting>('/v1/admin/model-routing', {
      revision,
      ordered_model_ids: orderedModelIds,
    });
    return response.data;
  } catch (error) {
    const detail = errorDetail(error, 'Failed to save model routing');
    throw new ModelRoutingRequestError(detail.message, detail.status, detail.reason);
  }
}

export async function checkChatGPTReadiness(): Promise<ChatGPTReadiness> {
  try {
    const response = await api.post<ChatGPTReadiness>('/v1/admin/model-routing/chatgpt-readiness');
    return response.data;
  } catch (error) {
    const detail = errorDetail(error, 'Failed to check ChatGPT readiness');
    throw new ModelRoutingRequestError(detail.message, detail.status, detail.reason);
  }
}
