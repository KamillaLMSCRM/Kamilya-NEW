export type VerificationStatus = 'active' | 'expired' | 'revoked';

export interface CertificateVerification {
  valid: boolean;
  status: VerificationStatus;
  certificate_number: string;
  issued_at: string;
  expires_at: string | null;
  user_name: string;
  course_title: string;
  organization_name: string;
  revoked_reason?: string | null;
}

export function normalizeCertificateNumber(value: string): string {
  return value.trim().toUpperCase();
}

export function getCertificateVerificationPath(number: string): string {
  return `/verify/certificate/${encodeURIComponent(normalizeCertificateNumber(number))}`;
}

export function formatVerificationDate(value: string | null, locale: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(date);
}

export async function fetchCertificateVerification(
  number: string,
  signal?: AbortSignal,
): Promise<CertificateVerification | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const normalized = normalizeCertificateNumber(number);
  const response = await fetch(`${apiUrl}/v1/certificates/verify/${encodeURIComponent(normalized)}`, {
    signal,
    cache: 'no-store',
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Verification request failed (${response.status})`);
  return response.json() as Promise<CertificateVerification>;
}
