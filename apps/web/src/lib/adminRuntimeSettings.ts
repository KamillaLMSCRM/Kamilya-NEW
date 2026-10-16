import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/apiErrorMessage';

export type RuntimeSettingKind = 'integer' | 'number' | 'boolean' | 'model';
export type RuntimeSettingValue = string | number | boolean;

export interface RuntimeSetting {
  key: string;
  label: string;
  kind: RuntimeSettingKind;
  value: RuntimeSettingValue;
  default: RuntimeSettingValue;
  overridden: boolean;
  minimum?: number | null;
  maximum?: number | null;
  choices?: string[] | null;
}

export interface RuntimeSettingsSnapshot {
  revision: number;
  settings: RuntimeSetting[];
  updated_at: string | null;
  propagation: string;
  cache_seconds: number;
}

export interface RuntimeSettingsHistoryEntry {
  revision: number;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
  created_at: string;
  actor_id: string | null;
}

export interface RuntimeSettingsHistoryResponse {
  history: RuntimeSettingsHistoryEntry[];
}

export class RuntimeSettingsRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'RuntimeSettingsRequestError';
  }
}

function requestError(error: unknown, fallback: string): RuntimeSettingsRequestError {
  const response = (error as { response?: { status?: number; data?: { code?: unknown; message?: unknown; detail?: unknown } } } | null)?.response;
  const detail = response?.data?.detail;
  const codeValue = response?.data?.code
    ?? (typeof detail === 'object' && detail !== null ? (detail as { code?: unknown }).code : detail)
    ?? response?.data?.message;
  const code = typeof codeValue === 'string' && /^runtime_settings_[a-z0-9_.:-]+$/.test(codeValue) ? codeValue : undefined;
  return new RuntimeSettingsRequestError(apiErrorMessage(error, fallback), response?.status ?? 0, code);
}

export async function getRuntimeSettings(): Promise<RuntimeSettingsSnapshot> {
  try {
    const response = await api.get<RuntimeSettingsSnapshot>('/v1/admin/runtime-settings');
    return response.data;
  } catch (error) {
    throw requestError(error, 'Failed to load runtime settings');
  }
}

export async function updateRuntimeSettings(
  revision: number,
  changes: Record<string, RuntimeSettingValue | null>,
  reason: string,
): Promise<RuntimeSettingsSnapshot> {
  try {
    const response = await api.put<RuntimeSettingsSnapshot>('/v1/admin/runtime-settings', {
      revision,
      changes,
      reason,
    });
    return response.data;
  } catch (error) {
    throw requestError(error, 'Failed to save runtime settings');
  }
}

export async function getRuntimeSettingsHistory(): Promise<RuntimeSettingsHistoryEntry[]> {
  try {
    const response = await api.get<RuntimeSettingsHistoryResponse | RuntimeSettingsHistoryEntry[]>('/v1/admin/runtime-settings/history');
    return Array.isArray(response.data) ? response.data : response.data.history;
  } catch (error) {
    throw requestError(error, 'Failed to load runtime settings history');
  }
}

export async function revertRuntimeSettings(
  revision: number,
  targetRevision: number,
  reason: string,
): Promise<RuntimeSettingsSnapshot> {
  try {
    const response = await api.post<RuntimeSettingsSnapshot>('/v1/admin/runtime-settings/revert', {
      revision,
      target_revision: targetRevision,
      reason,
    });
    return response.data;
  } catch (error) {
    throw requestError(error, 'Failed to revert runtime settings');
  }
}
