'use client';

import { Button, Badge, Modal } from '@/components/ui';
import { useT } from '@/i18n/useT';
import type { ChatGPTReadiness, GenerationModelRoute } from '@/lib/adminModelRouting';

const READINESS_REASONS = new Set(['not_configured', 'authorization_required', 'unavailable', 'protocol_mismatch', 'ready']);

interface Props {
  route?: GenerationModelRoute;
  readiness: ChatGPTReadiness | null;
  loading: boolean;
  loadError: boolean;
  checking: boolean;
  saving: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onCheck: () => void;
  onRetry: () => void;
  onEnable: () => void;
  onDisable: () => void;
}

export function ChatGPTReserveControl({
  route,
  readiness,
  loading,
  loadError,
  checking,
  saving,
  open,
  onOpen,
  onClose,
  onCheck,
  onRetry,
  onEnable,
  onDisable,
}: Props) {
  const { t } = useT();
  const enabled = Boolean(route?.is_enabled);
  const configured = Boolean(route?.is_configured);
  const candidateReason = readiness?.reason ?? route?.activation_blocker;
  const reason = candidateReason && READINESS_REASONS.has(candidateReason) ? candidateReason : 'unknown';
  const reasonKey = `providers.chatgptReserve.reasons.${reason}`;
  const translatedReason = (t as any)(reasonKey);
  const reasonText = translatedReason === reasonKey ? t('providers.chatgptReserve.reasonUnknown') : translatedReason;

  const requestEnable = () => {
    if (readiness?.ready && confirm(t('providers.chatgptReserve.confirmEnable'))) onEnable();
  };

  return (
    <>
      <Button type="button" variant="secondary" onClick={onOpen} aria-haspopup="dialog">
        {t('providers.chatgptReserve.button')}
      </Button>
      <Modal
        open={open}
        onClose={() => !loading && !saving && !checking && onClose()}
        title={t('providers.chatgptReserve.title')}
        description={t('providers.chatgptReserve.description')}
        dismissable={!loading && !saving && !checking}
      >
        {loading ? (
          <p className="py-6 text-center text-text-tertiary">…</p>
        ) : loadError ? (
          <div className="space-y-3 py-4 text-center">
            <p className="text-text-secondary">{t('providers.chatgptReserve.loadError')}</p>
            <Button type="button" variant="secondary" onClick={onRetry}>{t('providers.routingRetry')}</Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{t('providers.chatgptReserve.status')}</span>
              <Badge variant={enabled ? 'secondary' : 'default'}>
                {enabled ? t('providers.chatgptReserve.enabled') : t('providers.chatgptReserve.disabled')}
              </Badge>
            </div>
            <p className="text-sm text-text-secondary">
              {configured
                ? (enabled && readiness?.ready
                  ? t('providers.chatgptReserve.readyConfigured')
                  : t('providers.chatgptReserve.configured'))
                : t('providers.chatgptReserve.notConfigured')}
            </p>
            <p className="text-sm text-text-secondary" role="status">
              {readiness
                ? `${t('providers.chatgptReserve.readiness')}: ${reasonText}`
                : t('providers.chatgptReserve.readinessNotChecked')}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" onClick={onCheck} disabled={checking || saving}>
                {checking ? '…' : t('providers.chatgptReserve.checkReadiness')}
              </Button>
              {enabled ? (
                <Button type="button" variant="secondary" onClick={onDisable} disabled={saving}>
                  {saving ? '…' : t('providers.chatgptReserve.disable')}
                </Button>
              ) : (
                <Button type="button" onClick={requestEnable} disabled={saving || checking || !readiness?.ready}>
                  {saving ? '…' : t('providers.chatgptReserve.enable')}
                </Button>
              )}
            </div>
            <a
              className="text-sm underline"
              href="https://learn.chatgpt.com/docs/non-interactive-mode"
              target="_blank"
              rel="noreferrer"
            >
              {t('providers.chatgptReserve.docs')}
            </a>
            <p className="text-xs text-text-tertiary">{t('providers.chatgptReserve.docsWarning')}</p>
            <p className="text-xs text-text-tertiary">{t('providers.routingAppliesNextJobs')}</p>
          </div>
        )}
      </Modal>
    </>
  );
}
