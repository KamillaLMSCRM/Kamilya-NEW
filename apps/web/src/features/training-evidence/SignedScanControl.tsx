'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { Badge, Button, Input } from '@/components/ui';
import { CheckCircle2, Eye, RefreshCw, RotateCcw, Upload } from 'lucide-react';
import { api } from '@/lib/api';

const MAX_SIGNED_SCAN_BYTES = 10 * 1024 * 1024;
const ACCEPTED_SIGNED_SCAN_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
]);

export interface SignedScanLedger {
  event_id: string;
  status: 'awaiting_return' | 'uploaded_pending_review' | 'accepted' | 'replacement_requested';
  scans: Array<{
    id: string;
    original_filename: string;
    content_type: string;
    uploaded_at: string;
    status: 'uploaded_pending_review' | 'accepted' | 'replacement_requested';
    latest_review_reason?: string | null;
  }>;
}

interface SignedScanLedgersState {
  ledgers: Record<string, SignedScanLedger | undefined>;
  errors: Record<string, string | undefined>;
  loadingEventIds: Set<string>;
  uploadingEventIds: Set<string>;
  reviewingScanIds: Set<string>;
  refresh: (eventId: string) => Promise<void>;
  upload: (eventId: string, file: File) => Promise<void>;
  review: (eventId: string, scanId: string, action: 'accept' | 'request_replacement', reason?: string) => Promise<void>;
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
  const [reviewingScanIds, setReviewingScanIds] = useState<Set<string>>(new Set());
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

  const review = useCallback(async (
    eventId: string,
    scanId: string,
    action: 'accept' | 'request_replacement',
    reason?: string,
  ) => {
    setReviewingScanIds((current) => new Set(current).add(scanId));
    setErrors((current) => ({ ...current, [eventId]: undefined }));
    try {
      await api.post(`/v1/training-evidence/events/${eventId}/signed-scans/${scanId}/review`, {
        action,
        reason: action === 'request_replacement' ? reason : null,
      });
      await refresh(eventId);
    } catch (error: any) {
      const detail = error?.response?.data?.message || error?.response?.data?.detail;
      setErrors((current) => ({
        ...current,
        [eventId]: typeof detail === 'string' ? detail : 'Не удалось сохранить решение по экземпляру.',
      }));
    } finally {
      setReviewingScanIds((current) => {
        const next = new Set(current);
        next.delete(scanId);
        return next;
      });
    }
  }, [refresh]);

  return { ledgers, errors, loadingEventIds, uploadingEventIds, reviewingScanIds, refresh, upload, review };
}

export function SignedScanControl({
  eventId,
  ledger,
  loading,
  uploading,
  error,
  onRetry,
  onUpload,
  reviewingScanIds,
  onReview,
}: {
  eventId: string;
  ledger: SignedScanLedger | undefined;
  loading: boolean;
  uploading: boolean;
  error: string | undefined;
  onRetry: () => void;
  onUpload: (file: File) => Promise<void>;
  reviewingScanIds: Set<string>;
  onReview: (scanId: string, action: 'accept' | 'request_replacement', reason?: string) => Promise<void>;
}) {
  const [replacementReasons, setReplacementReasons] = useState<Record<string, string>>({});
  const [openingScanId, setOpeningScanId] = useState<string | null>(null);
  const received = Boolean(ledger?.scans.length);
  const inputId = `signed-scan-${eventId}`;

  const openScan = async (scanId: string) => {
    setOpeningScanId(scanId);
    try {
      const response = await api.get<Blob>(
        `/v1/training-evidence/events/${eventId}/signed-scans/${scanId}/download`,
        { responseType: 'blob' },
      );
      const url = URL.createObjectURL(response.data);
      window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } finally {
      setOpeningScanId(null);
    }
  };

  const statusLabel = {
    awaiting_return: 'Ожидается подписанный экземпляр',
    uploaded_pending_review: 'Загружен — ожидает проверки',
    accepted: 'Подписанный экземпляр принят',
    replacement_requested: 'Запрошена замена экземпляра',
  }[ledger?.status || 'awaiting_return'];

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`signed-scan-${eventId}`}>
      <Badge variant={ledger?.status === 'accepted' ? 'default' : 'secondary'}>
        {loading && !ledger ? 'Проверяем экземпляр…' : statusLabel}
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
      {ledger?.scans.map((scan) => (
        <div key={scan.id} className="w-full space-y-2 rounded-md border border-border bg-muted/20 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{scan.original_filename}</p>
              <p className="text-xs text-muted-foreground">
                {new Date(scan.uploaded_at).toLocaleString('ru-RU')}
              </p>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => void openScan(scan.id)} disabled={openingScanId === scan.id}>
              {openingScanId === scan.id ? <RefreshCw className="mr-1 h-4 w-4 animate-spin" /> : <Eye className="mr-1 h-4 w-4" />}
              Открыть
            </Button>
          </div>
          {scan.status === 'uploaded_pending_review' && (
            <div className="space-y-2">
              <Input
                value={replacementReasons[scan.id] || ''}
                onChange={(event) => setReplacementReasons((current) => ({ ...current, [scan.id]: event.target.value }))}
                placeholder="Причина замены: неразборчиво, нет подписи, не все страницы…"
                maxLength={2000}
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => void onReview(scan.id, 'accept')} disabled={reviewingScanIds.has(scan.id)}>
                  <CheckCircle2 className="mr-1 h-4 w-4" /> Принять
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void onReview(scan.id, 'request_replacement', replacementReasons[scan.id]?.trim())}
                  disabled={reviewingScanIds.has(scan.id) || !replacementReasons[scan.id]?.trim()}
                >
                  <RotateCcw className="mr-1 h-4 w-4" /> Запросить замену
                </Button>
              </div>
            </div>
          )}
          {scan.status === 'accepted' && <p className="text-sm text-success">Принят методистом</p>}
          {scan.status === 'replacement_requested' && (
            <p className="text-sm text-destructive">Запрошена замена: {scan.latest_review_reason}</p>
          )}
        </div>
      ))}
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
