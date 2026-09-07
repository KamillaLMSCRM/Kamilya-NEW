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

async function parseResponse(response: Response): Promise<GenerationModelRouting> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
    throw new ModelRoutingRequestError(body.detail || `HTTP ${response.status}`, response.status);
  }
  return response.json();
}

export async function getGenerationModelRouting(
  apiUrl: string | undefined,
  token: string,
): Promise<GenerationModelRouting> {
  const response = await fetch(`${apiUrl}/admin/model-routing`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return parseResponse(response);
}

export async function saveGenerationModelRouting(
  apiUrl: string | undefined,
  token: string,
  revision: number,
  orderedModelIds: string[],
): Promise<GenerationModelRouting> {
  const response = await fetch(`${apiUrl}/admin/model-routing`, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ revision, ordered_model_ids: orderedModelIds }),
  });
  return parseResponse(response);
}
