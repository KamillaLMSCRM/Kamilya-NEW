import { api } from '@/lib/api';

export type EvidenceShareFormat = 'zip' | 'pdf';

export interface EvidenceShare {
  id: string;
  format: EvidenceShareFormat;
  package_sha256: string;
  package_size_bytes: number;
  source_event_count: number;
  expires_at: string;
  max_downloads: number;
  download_count: number;
  revoked_at: string | null;
  created_at: string;
  url?: string | null;
}

export async function createEvidenceShare(
  eventIds: string[],
  format: EvidenceShareFormat,
  expiresAt: string,
  maxDownloads: number,
): Promise<EvidenceShare> {
  const response = await api.post<EvidenceShare>('/v1/training-evidence/shares', {
    event_ids: eventIds,
    format,
    expires_at: expiresAt,
    max_downloads: maxDownloads,
  });
  return response.data;
}

export async function revokeEvidenceShare(shareId: string): Promise<Pick<EvidenceShare, 'id' | 'revoked_at'>> {
  const response = await api.post<Pick<EvidenceShare, 'id' | 'revoked_at'>>(`/v1/training-evidence/shares/${shareId}/revoke`);
  return response.data;
}
