/** Display only server messages, never request configs, inputs or credentials. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { detail?: unknown; error?: unknown }; status?: number } } | null)?.response;
  const detail = response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.slice(0, 5).flatMap((item: unknown) => {
      if (!item || typeof item !== 'object') return [];
      const message = (item as { msg?: unknown }).msg;
      return typeof message === 'string' && message ? [message.slice(0, 500)] : [];
    });
    if (messages.length) return messages.join('; ');
  }
  if (typeof response?.data?.error === 'string' && response.data.error) return response.data.error;
  if (response?.status) return `HTTP ${response.status}`;
  return fallback;
}
