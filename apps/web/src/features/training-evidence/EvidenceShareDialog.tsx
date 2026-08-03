'use client';

import { useEffect, useState } from 'react';
import { Copy, Link2, RefreshCw, ShieldOff } from 'lucide-react';
import { Button, Input, Modal } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import {
  createEvidenceShare,
  revokeEvidenceShare,
  type EvidenceShare,
  type EvidenceShareFormat,
} from './shareApi';

interface EvidenceShareDialogProps {
  open: boolean;
  eventIds: string[];
  onClose: () => void;
}

function defaultExpiry(): string {
  const expiry = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
  const offset = expiry.getTimezoneOffset() * 60 * 1000;
  return new Date(expiry.getTime() - offset).toISOString().slice(0, 16);
}

export function EvidenceShareDialog({ open, eventIds, onClose }: EvidenceShareDialogProps) {
  const { t, lang } = useT();
  const [format, setFormat] = useState<EvidenceShareFormat>('zip');
  const [expiresAt, setExpiresAt] = useState(defaultExpiry);
  const [maxDownloads, setMaxDownloads] = useState('3');
  const [share, setShare] = useState<EvidenceShare | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const eventIdsKey = eventIds.join(',');
  const dateLocale = lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-US' : 'ru-RU';

  useEffect(() => {
    if (open) {
      setShare(null);
      setCopied(false);
      setExpiresAt(defaultExpiry());
      setMaxDownloads('3');
    }
  }, [open, eventIdsKey]);

  const create = async () => {
    const parsedMaxDownloads = Number(maxDownloads);
    if (!Number.isInteger(parsedMaxDownloads) || parsedMaxDownloads < 1 || parsedMaxDownloads > 100) {
      toast.error(t('trainingLog.evidence.share.errors.invalidDownloads'));
      return;
    }
    const parsedExpiry = new Date(expiresAt);
    if (Number.isNaN(parsedExpiry.getTime()) || parsedExpiry <= new Date()) {
      toast.error(t('trainingLog.evidence.share.errors.invalidExpiry'));
      return;
    }
    setBusy(true);
    try {
      const created = await createEvidenceShare(
        eventIds,
        format,
        parsedExpiry.toISOString(),
        parsedMaxDownloads,
      );
      setShare(created);
      toast.success(t('trainingLog.evidence.share.toasts.created'));
    } catch {
      toast.error(t('trainingLog.evidence.share.errors.create'));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!share?.url) return;
    try {
      await navigator.clipboard.writeText(share.url);
      setCopied(true);
      toast.success(t('trainingLog.evidence.share.toasts.copied'));
    } catch {
      toast.error(t('trainingLog.evidence.share.errors.copy'));
    }
  };

  const revoke = async () => {
    if (!share) return;
    setBusy(true);
    try {
      const revoked = await revokeEvidenceShare(share.id);
      setShare({ ...share, revoked_at: revoked.revoked_at });
      toast.success(t('trainingLog.evidence.share.toasts.revoked'));
    } catch {
      toast.error(t('trainingLog.evidence.share.errors.revoke'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('trainingLog.evidence.share.title')}
      description={t('trainingLog.evidence.share.description')}
      className="max-w-xl max-h-[90vh] overflow-y-auto"
    >
      {!share ? (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {t('trainingLog.evidence.share.selectedRecords', { count: eventIds.length })}
          </p>
          <div>
            <label htmlFor="evidence-share-format" className="mb-1 block text-sm font-medium">
              {t('trainingLog.evidence.share.format')}
            </label>
            <select
              id="evidence-share-format"
              value={format}
              onChange={(event) => setFormat(event.target.value as EvidenceShareFormat)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="zip">{t('trainingLog.evidence.share.formats.zip')}</option>
              <option value="pdf">{t('trainingLog.evidence.share.formats.pdf')}</option>
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="evidence-share-expires-at" className="mb-1 block text-sm font-medium">
                {t('trainingLog.evidence.share.expiresAt')}
              </label>
              <Input
                id="evidence-share-expires-at"
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="evidence-share-max-downloads" className="mb-1 block text-sm font-medium">
                {t('trainingLog.evidence.share.maxDownloads')}
              </label>
              <Input
                id="evidence-share-max-downloads"
                type="number"
                min={1}
                max={100}
                value={maxDownloads}
                onChange={(event) => setMaxDownloads(event.target.value)}
                aria-describedby="evidence-share-max-downloads-help"
              />
              <p id="evidence-share-max-downloads-help" className="mt-1 text-xs text-muted-foreground">
                {t('trainingLog.evidence.share.maxDownloadsHint')}
              </p>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>{t('trainingLog.evidence.share.cancel')}</Button>
            <Button type="button" onClick={() => void create()} disabled={busy || eventIds.length === 0}>
              {busy ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : <Link2 className="mr-2 h-4 w-4" aria-hidden="true" />}
              {t('trainingLog.evidence.share.createLink')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
            <div className="font-medium text-foreground">{t('trainingLog.evidence.share.ready')}</div>
            <div className="mt-1 text-muted-foreground">
              {t('trainingLog.evidence.share.details', {
                date: new Date(share.expires_at).toLocaleString(dateLocale),
                count: share.max_downloads,
              })}
            </div>
          </div>
          <Input
            readOnly
            value={share.revoked_at ? t('trainingLog.evidence.share.revoked') : (share.url || '')}
            aria-label={t('trainingLog.evidence.share.linkAriaLabel')}
          />
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>{t('trainingLog.evidence.share.close')}</Button>
            {!share.revoked_at && (
              <>
                <Button type="button" variant="outline" onClick={() => void copy()} disabled={!share.url || busy}>
                  <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
                  {copied ? t('trainingLog.evidence.share.copied') : t('trainingLog.evidence.share.copy')}
                </Button>
                <Button type="button" variant="outline" onClick={() => void revoke()} disabled={busy}>
                  {busy ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : <ShieldOff className="mr-2 h-4 w-4" aria-hidden="true" />}
                  {t('trainingLog.evidence.share.revoke')}
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
