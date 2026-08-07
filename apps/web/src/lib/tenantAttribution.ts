export interface TenantAttribution {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  utm_term?: string;
  referrer?: string;
}

const LIMITS: Record<keyof TenantAttribution, number> = {
  utm_source: 100,
  utm_medium: 100,
  utm_campaign: 100,
  utm_content: 100,
  utm_term: 100,
  referrer: 500,
};

export function extractTenantAttribution(
  search: string,
  documentReferrer = '',
): TenantAttribution {
  const params = new URLSearchParams(search);
  const result: TenantAttribution = {};

  for (const key of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'] as const) {
    const value = params.get(key)?.trim();
    if (value) result[key] = value.slice(0, LIMITS[key]);
  }

  const referrer = params.get('referrer')?.trim() || documentReferrer.trim();
  if (referrer) result.referrer = referrer.slice(0, LIMITS.referrer);
  return result;
}
