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
}

export interface GenerationModelRouting {
  revision: number;
  models: GenerationModelRoute[];
  updated_at: string;
}

export class ModelRoutingRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

function errorDetail(error: unknown, fallback: string) {
  const response = (error as { response?: { data?: { detail?: unknown }; status?: number } } | null)?.response;
  return {
    message: apiErrorMessage(error, fallback),
    status: response?.status ?? 0,
  };
}

export async function getGenerationModelRouting(): Promise<GenerationModelRouting> {
  try {
    const response = await api.get<GenerationModelRouting>('/v1/admin/model-routing');
    return response.data;
  } catch (error) {
    const detail = errorDetail(error, 'Failed to load model routing');
    throw new ModelRoutingRequestError(detail.message, detail.status);
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
    throw new ModelRoutingRequestError(detail.message, detail.status);
  }
}
