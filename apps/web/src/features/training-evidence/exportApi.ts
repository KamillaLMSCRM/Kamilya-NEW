import { api } from '@/lib/api';

export type EvidenceExportFormat = 'pdf' | 'zip';

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function downloadIndividualEvidence(eventId: string, format: EvidenceExportFormat): Promise<void> {
  const response = await api.get<Blob>(`/v1/training-evidence/events/${eventId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  saveBlob(response.data, `kamilya-training-evidence-${eventId}.${format}`);
}

export async function downloadGroupEvidence(eventIds: string[], format: EvidenceExportFormat): Promise<void> {
  const response = await api.post<Blob>('/v1/training-evidence/exports/group', {
    event_ids: eventIds,
    format,
  }, { responseType: 'blob' });
  saveBlob(response.data, `kamilya-training-evidence-group.${format}`);
}
