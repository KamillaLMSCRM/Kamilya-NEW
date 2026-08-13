'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Badge } from '@/components/ui';
import { RefreshCw, Upload } from 'lucide-react';
import { api } from '@/lib/api';

const MAX_SIGNED_SCAN_BYTES = 10 * 1024 * 1024;
const ACCEPTED_SIGNED_SCAN_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
]);

export interface SignedScanLedger {
  event_id: string;
  status: 'awaiting_signed_copy' | 'received';
  scans: Array<{
    id: string;
    original_filename: string;
  }>;
}

interface SignedScanLedgersState {
  ledgers: Record<string, SignedScanLedger | undefined>;
  errors: Record<string, string | undefined>;
  loadingEventIds: Set<string>;
  uploadingEventIds: Set<string>;
  refresh: (eventId: string) => Promise<void>;
  upload: (eventId: string, file: File) => Promise<void>;
}

function signedScanError(error: any, operation: 'load' | 'upload'): string {
  const status = error?.response?.status;
  if (status === 413) return 'Подписанный экземпляр превышает 10 МБ.';
  if (status === 422) return 'Выберите PDF, JPEG или PNG размером до 10 МБ.';
  if (status === 404) return 'Документ о прохождении больше недоступен. Обновите журнал обучения.';
  return operation === 'load'
    ? 'Не удалось проверить статус подписанного экземпляра. Повторите попытку.'
    : 'Не удалось прикрепить подписанный экземпляр. Повторите попытку.';
}

function validateSignedScan(file: File): string | null {
  if (!ACCEPTED_SIGNED_SCAN_TYPES.has(file.type) || file.size > MAX_SIGNED_SCAN_BYTES) {
    return 'Выберите PDF, JPEG или PNG размером до 10 МБ.';
  }
  return null;
}

export function useSignedScanLedgers(
  eventIds: string[],
  enabled: boolean,
): SignedScanLedgersState {
  const [ledgers, setLedgers] = useState<Record<string, SignedScanLedger | undefined>>({});
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const [loadingEventIds, setLoadingEventIds] = useState<Set<string>>(new Set());
  const [uploadingEventIds, setUploadingEventIds] = useState<Set<string>>(new Set());
  const eventIdsKey = useMemo(() => Array.from(new Set(eventIds)).sort().join(','), [eventIds]);

  const refresh = useCallback(async (eventId: string) => {
    setLoadingEventIds((current) => new Set(current).add(eventId));
    setErrors((current) => ({ ...current, [eventId]: undefined }));
    try {
      const response = await api.get<SignedScanLedger>(
        `/v1/training-evidence/events/${eventId}/signed-scans`,
      );
      setLedgers((current) => ({ ...current, [eventId]: response.data }));
    } catch (error) {
      setErrors((current) => ({ ...current, [eventId]: signedScanError(error, 'load') }));
    } finally {
      setLoadingEventIds((current) => {
        const next = new Set(current);
        next.delete(eventId);
        return next;
      });
    }
  }, []);

  useEffect(() => {
    if (!enabled || !eventIdsKey) return;
    for (const eventId of eventIdsKey.split(',')) {
      void refresh(eventId);
    }
  }, [enabled, eventIdsKey, refresh]);

  const upload = useCallback(async (eventId: string, file: File) => {
    const validationError = validateSignedScan(file);
    if (validationError) {
      setErrors((current) => ({ ...current, [eventId]: validationError }));
      return;
    }

    setUploadingEventIds((current) => new Set(current).add(eventId));
    setErrors((current) => ({ ...current, [eventId]: undefined }));
    const formData = new FormData();
    formData.append('file', file);
    try {
      await api.post(`/v1/training-evidence/events/${eventId}/signed-scans`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await refresh(eventId);
    } catch (error) {
      setErrors((current) => ({ ...current, [eventId]: signedScanError(error, 'upload') }));
    } finally {
      setUploadingEventIds((current) => {
        const next = new Set(current);
        next.delete(eventId);
        return next;
      });
    }
  }, [refresh]);

  return { ledgers, errors, loadingEventIds, uploadingEventIds, refresh, upload };
}

export function SignedScanControl({
  eventId,
  ledger,
  loading,
  uploading,
  error,
  onRetry,
  onUpload,
}: {
  eventId: string;
  ledger: SignedScanLedger | undefined;
  loading: boolean;
  uploading: boolean;
  error: string | undefined;
  onRetry: () => void;
  onUpload: (file: File) => Promise<void>;
}) {
  const received = ledger?.status === 'received';
  const inputId = `signed-scan-${eventId}`;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`signed-scan-${eventId}`}>
      <Badge variant={received ? 'default' : 'secondary'}>
        {loading && !ledger
          ? 'Проверяем экземпляр…'
          : received
            ? 'Подписанный экземпляр получен'
            : 'Ожидается подписанный экземпляр'}
      </Badge>
      <label
        htmlFor={inputId}
        className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-input px-3 text-sm font-medium text-foreground hover:bg-accent focus-within:ring-2 focus-within:ring-ring disabled:cursor-not-allowed"
      >
        {uploading ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Upload className="h-4 w-4" aria-hidden="true" />}
        {uploading ? 'Загрузка…' : received ? 'Добавить скан' : 'Прикрепить скан'}
        <input
          id={inputId}
          type="file"
          className="sr-only"
          accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png"
          disabled={uploading}
          aria-label="Подписанный экземпляр: PDF, JPEG или PNG до 10 МБ"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void onUpload(file);
          }}
        />
      </label>
      <span className="text-xs text-muted-foreground">PDF, JPEG или PNG · до 10 МБ</span>
      {error && (
        <div className="flex items-center gap-2 text-xs text-destructive" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetry} className="font-medium underline hover:no-underline">
            Повторить
          </button>
        </div>
      )}
    </div>
  );
}
