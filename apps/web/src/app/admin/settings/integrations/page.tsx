'use client';

/**
 * /admin/settings/integrations — настройка каналов доставки уведомлений.
 *
 * Три канала: WhatsApp (wa-gateway), SMTP (свой почтовый сервер), Telegram
 * (свой бот). Все credentials — от тенанта, Kamilya только middleware
 * (ADR-0010). Страница показывает текущее состояние каждого канала и
 * предоставляет UI для настройки / тестирования.
 *
 * Только admin / org_admin / superadmin (role check в backend).
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card,
  CardContent,
  Button,
  Badge,
  Input,
} from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import {
  Mail,
  Send,
  MessageCircle,
  Wifi,
  WifiOff,
  RefreshCw,
  Trash2,
  ExternalLink,
  AlertTriangle,
  CheckCircle2,
  Clock,
  XCircle,
} from 'lucide-react';
import {
  initWhatsApp,
  getWhatsAppStatus,
  logoutWhatsApp,
  testWhatsApp,
  setSMTP,
  testSMTP,
  setTelegram,
  testTelegram,
  listIntegrations,
  type IntegrationSummary,
  type WhatsAppStatus,
  type SMTPConfig,
} from '@/features/integrations/api';

type Tab = 'whatsapp' | 'smtp' | 'telegram';

export default function IntegrationsPage() {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const [tab, setTab] = useState<Tab>('whatsapp');
  const [summary, setSummary] = useState<IntegrationSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      setSummary(await listIntegrations(token));
    } catch (e) {
      toast.error(`Не удалось загрузить список: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    reload();
  }, [reload]);

  const getSummary = (channel: Tab) =>
    summary.find((s) => s.channel === channel);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{t('integrations.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t('integrations.subtitle')}
        </p>
      </div>

      {/* Disclaimer — Kamilya = middleware, tenant owns everything */}
      <div className="rounded-lg border border-amber-300/60 bg-amber-50/40 dark:bg-amber-950/20 p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
        <div className="text-sm text-amber-900 dark:text-amber-200">
          <div className="font-medium mb-1">{t('integrations.disclaimerTitle')}</div>
          <p className="text-amber-800/90 dark:text-amber-300/80">
            {t('integrations.disclaimerBody')}
          </p>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="inline-flex rounded-md border border-border/60 bg-muted/40 p-0.5 text-sm">
        <ChannelTab
          active={tab === 'whatsapp'}
          onClick={() => setTab('whatsapp')}
          icon={<MessageCircle size={14} />}
          label={t('integrations.tab.whatsapp')}
          summary={getSummary('whatsapp')}
        />
        <ChannelTab
          active={tab === 'smtp'}
          onClick={() => setTab('smtp')}
          icon={<Mail size={14} />}
          label={t('integrations.tab.smtp')}
          summary={getSummary('smtp')}
        />
        <ChannelTab
          active={tab === 'telegram'}
          onClick={() => setTab('telegram')}
          icon={<Send size={14} />}
          label={t('integrations.tab.telegram')}
          summary={getSummary('telegram')}
        />
      </div>

      {loading ? (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            {t('common.loading')}
          </CardContent>
        </Card>
      ) : (
        <>
          {tab === 'whatsapp' && <WhatsAppPanel onChange={reload} summary={getSummary('whatsapp')} />}
          {tab === 'smtp' && <SMTPPanel onChange={reload} summary={getSummary('smtp')} />}
          {tab === 'telegram' && <TelegramPanel onChange={reload} summary={getSummary('telegram')} />}
        </>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────


function ChannelTab({
  active,
  onClick,
  icon,
  label,
  summary,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  summary?: IntegrationSummary;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded ${
        active ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'
      }`}
    >
      {icon}
      {label}
      {summary && <StatusDot summary={summary} />}
    </button>
  );
}

function StatusDot({ summary }: { summary: IntegrationSummary }) {
  if (!summary.is_active) {
    return <span className="ml-1 w-2 h-2 rounded-full bg-gray-400" title="inactive" />;
  }
  // Channel-specific status interpretation
  const extra = summary.extra as Record<string, unknown> | undefined;
  const ok =
    summary.channel === 'whatsapp'
      ? extra?.status === 'connected'
      : summary.channel === 'smtp'
        ? (summary.last_test_status ?? '').startsWith('ok')
        : (summary.last_test_status ?? '').startsWith('ok');

  if (ok) return <span className="ml-1 w-2 h-2 rounded-full bg-emerald-500" title="ok" />;
  return <span className="ml-1 w-2 h-2 rounded-full bg-amber-500" title="needs attention" />;
}

// ── WhatsApp Panel ────────────────────────────────────────────────────────


function WhatsAppPanel({
  onChange,
  summary,
}: {
  onChange: () => void;
  summary?: IntegrationSummary;
}) {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const [status, setStatus] = useState<WhatsAppStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const s = await getWhatsAppStatus(token);
      setStatus(s);
      setLoading(false);
    } catch (e) {
      toast.error(t('integrations.whatsapp.loadError', { error: (e as Error).message }));
      setLoading(false);
    }
  }, [token, t]);

  useEffect(() => {
    refresh();
    // Poll every 3s while we're waiting for QR / connection
    pollRef.current = setInterval(() => {
      if (status && ['initializing', 'qr_pending', 'disconnected'].includes(status.status)) {
        refresh();
      }
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh, status]);

  // Stop polling when connected
  useEffect(() => {
    if (status?.status === 'connected' && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      onChange();
    }
  }, [status, onChange]);

  const handleInit = async () => {
    if (!token) return;
    setSubmitting(true);
    try {
      const result = await initWhatsApp(token);
      toast.success(
        result.status === 'connected'
          ? t('integrations.whatsapp.alreadyConnected')
          : t('integrations.whatsapp.qrGenerated')
      );
      await refresh();
      onChange();
    } catch (e) {
      toast.error(`Init failed: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!token) return;
    setTesting(true);
    try {
      const r = await testWhatsApp(token);
      toast.success(r.detail);
      onChange();
    } catch (e) {
      toast.error(t('integrations.whatsapp.testFailed', { error: (e as Error).message }));
    } finally {
      setTesting(false);
    }
  };

  const handleLogout = async () => {
    if (!token) return;
    if (!confirm(t('integrations.whatsapp.logoutConfirm'))) return;
    setSubmitting(true);
    try {
      await logoutWhatsApp(token);
      toast.success(t('integrations.whatsapp.logoutSuccess'));
      await refresh();
      onChange();
    } catch (e) {
      toast.error(`Logout failed: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const isConnected = status?.status === 'connected';
  const isPending = status && ['initializing', 'qr_pending'].includes(status.status);
  const hasQr = !!status?.qr;

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2">
              <MessageCircle size={18} className="text-emerald-600" />
              {t('integrations.whatsapp.title')}
              {isConnected && <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">{t('integrations.whatsapp.connected')}</Badge>}
              {isPending && <Badge variant="secondary"><Clock size={10} className="mr-1" />{t('integrations.whatsapp.pending')}</Badge>}
              {status?.status === 'disconnected' && <Badge variant="destructive"><WifiOff size={10} className="mr-1" />{t('integrations.whatsapp.disconnected')}</Badge>}
              {status?.status === 'logged_out' && <Badge variant="secondary"><XCircle size={10} className="mr-1" />{t('integrations.whatsapp.loggedOut')}</Badge>}
              {status?.status === 'not_started' && <Badge variant="outline">{t('integrations.whatsapp.notStarted')}</Badge>}
            </h3>
            <p className="text-sm text-muted-foreground mt-1">
              {t('integrations.whatsapp.description')}
            </p>
          </div>
          <a
            href="https://github.com/whiskeysockets/Baileys"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
          >
            Baileys <ExternalLink size={10} />
          </a>
        </div>

        {/* Status info */}
        {loading ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : isConnected ? (
          <ConnectedView
            status={status!}
            onTest={handleTest}
            onLogout={handleLogout}
            testing={testing}
            submitting={submitting}
          />
        ) : isPending ? (
          <PendingView
            status={status!}
            onInit={handleInit}
            onRefresh={refresh}
            submitting={submitting}
          />
        ) : (
          <NotStartedView
            onInit={handleInit}
            submitting={submitting}
          />
        )}
      </CardContent>
    </Card>
  );
}

function ConnectedView({
  status,
  onTest,
  onLogout,
  testing,
  submitting,
}: {
  status: WhatsAppStatus;
  onTest: () => void;
  onLogout: () => void;
  testing: boolean;
  submitting: boolean;
}) {
  const { t } = useT();
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-md bg-emerald-50/60 dark:bg-emerald-950/20 px-3 py-2 text-sm border border-emerald-200/50">
        <CheckCircle2 size={16} className="text-emerald-600" />
        <span className="font-medium text-emerald-900 dark:text-emerald-200">
          {t('integrations.whatsapp.connectedTo', { phone: status.phone_number ?? '' })}
        </span>
      </div>
      <div className="flex gap-2">
        <Button onClick={onTest} disabled={testing || submitting}>
          {testing ? t('integrations.whatsapp.testing') : t('integrations.whatsapp.sendTest')}
        </Button>
        <Button variant="outline" onClick={onLogout} disabled={submitting}>
          <Trash2 size={14} className="mr-1" />
          {t('integrations.whatsapp.disconnect')}
        </Button>
      </div>
    </div>
  );
}

function PendingView({
  status,
  onInit,
  onRefresh,
  submitting,
}: {
  status: WhatsAppStatus;
  onInit: () => void;
  onRefresh: () => void;
  submitting: boolean;
}) {
  const { t } = useT();
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-md bg-amber-50/60 dark:bg-amber-950/20 px-3 py-2 text-sm border border-amber-200/50">
        <Clock size={16} className="text-amber-600" />
        <span className="font-medium text-amber-900 dark:text-amber-200">
          {status.status === 'qr_pending' && status.qr
            ? t('integrations.whatsapp.scanQR')
            : t('integrations.whatsapp.initializing')}
        </span>
      </div>

      {status.qr ? (
        <div className="rounded-md border border-border bg-white p-4 inline-block">
          <img
            src={`data:image/png;base64,${status.qr}`}
            alt="WhatsApp QR code"
            className="w-64 h-64 block"
          />
          <p className="text-xs text-muted-foreground mt-2 text-center max-w-xs">
            {t('integrations.whatsapp.qrHint')}
          </p>
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border/60 p-8 text-center text-sm text-muted-foreground">
          <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin" />
          {t('integrations.whatsapp.waitingForQR')}
        </div>
      )}

      <div className="flex gap-2">
        <Button onClick={onInit} disabled={submitting}>
          {t('integrations.whatsapp.regenerateQR')}
        </Button>
        <Button variant="ghost" onClick={onRefresh}>
          <RefreshCw size={14} className="mr-1" />
          {t('integrations.whatsapp.refresh')}
        </Button>
      </div>
    </div>
  );
}

function NotStartedView({
  onInit,
  submitting,
}: {
  onInit: () => void;
  submitting: boolean;
}) {
  const { t } = useT();
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-muted/30 p-4 text-sm text-muted-foreground space-y-2">
        <p>{t('integrations.whatsapp.howToConnect')}</p>
        <ol className="list-decimal list-inside space-y-1 pl-1">
          <li>{t('integrations.whatsapp.step1')}</li>
          <li>{t('integrations.whatsapp.step2')}</li>
          <li>{t('integrations.whatsapp.step3')}</li>
          <li>{t('integrations.whatsapp.step4')}</li>
        </ol>
      </div>
      <Button onClick={onInit} disabled={submitting}>
        <MessageCircle size={14} className="mr-1" />
        {t('integrations.whatsapp.connect')}
      </Button>
    </div>
  );
}

// ── SMTP Panel ────────────────────────────────────────────────────────────


function SMTPPanel({
  onChange,
  summary,
}: {
  onChange: () => void;
  summary?: IntegrationSummary;
}) {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const [host, setHost] = useState('');
  const [port, setPort] = useState('587');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fromAddr, setFromAddr] = useState('');
  const [fromName, setFromName] = useState('');
  const [useTls, setUseTls] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);

  const isConfigured = summary?.is_active ?? false;

  const handleSave = async () => {
    if (!token) return;
    if (!host || !username || !password || !fromAddr) {
      toast.error(t('integrations.smtp.fillRequired'));
      return;
    }
    setSubmitting(true);
    try {
      await setSMTP(token, {
        host,
        port: parseInt(port, 10),
        username,
        password,
        from_addr: fromAddr,
        from_name: fromName,
        use_tls: useTls,
      });
      toast.success(t('integrations.smtp.saved'));
      setPassword(''); // clear after save
      onChange();
    } catch (e) {
      toast.error(`SMTP save failed: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!token) return;
    setTesting(true);
    try {
      const r = await testSMTP(token);
      toast.success(r.detail);
      onChange();
    } catch (e) {
      toast.error(`SMTP test failed: ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div>
          <h3 className="font-semibold text-lg flex items-center gap-2">
            <Mail size={18} className="text-blue-600" />
            {t('integrations.smtp.title')}
            {isConfigured && (
              <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
                {t('integrations.smtp.configured')}
              </Badge>
            )}
          </h3>
          <p className="text-sm text-muted-foreground mt-1">
            {t('integrations.smtp.description')}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label={t('integrations.smtp.host')} required>
            <Input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="smtp.gmail.com"
            />
          </Field>
          <Field label={t('integrations.smtp.port')}>
            <Input
              type="number"
              value={port}
              onChange={(e) => setPort(e.target.value)}
            />
          </Field>
          <Field label={t('integrations.smtp.username')} required>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="lms@company.kz"
            />
          </Field>
          <Field label={t('integrations.smtp.password')} required>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isConfigured ? '••••••••' : ''}
            />
          </Field>
          <Field label={t('integrations.smtp.fromAddr')} required>
            <Input
              type="email"
              value={fromAddr}
              onChange={(e) => setFromAddr(e.target.value)}
              placeholder="noreply@company.kz"
            />
          </Field>
          <Field label={t('integrations.smtp.fromName')}>
            <Input
              value={fromName}
              onChange={(e) => setFromName(e.target.value)}
              placeholder="Kamilya LMS"
            />
          </Field>
        </div>

        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useTls}
            onChange={(e) => setUseTls(e.target.checked)}
          />
          {t('integrations.smtp.useTls')}
        </label>

        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={submitting || testing}>
            {submitting ? t('common.saving') : t('common.save')}
          </Button>
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={!isConfigured || submitting || testing}
            title={!isConfigured ? t('integrations.smtp.saveFirst') : ''}
          >
            {testing ? t('integrations.smtp.testing') : t('integrations.smtp.sendTest')}
          </Button>
        </div>

        {summary?.last_test_at && (
          <p className="text-xs text-muted-foreground">
            {t('integrations.lastTest', {
              date: new Date(summary.last_test_at).toLocaleString('ru-RU'),
              status: summary.last_test_status ?? '',
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Telegram Panel ────────────────────────────────────────────────────────


function TelegramPanel({
  onChange,
  summary,
}: {
  onChange: () => void;
  summary?: IntegrationSummary;
}) {
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const [botToken, setBotToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);

  const isConfigured = summary?.is_active ?? false;

  const handleSave = async () => {
    if (!token) return;
    if (!botToken || !/^\d+:[A-Za-z0-9_-]+$/.test(botToken)) {
      toast.error(t('integrations.telegram.invalidToken'));
      return;
    }
    setSubmitting(true);
    try {
      await setTelegram(token, { bot_token: botToken });
      toast.success(t('integrations.telegram.saved'));
      setBotToken('');
      onChange();
    } catch (e) {
      toast.error(`Telegram save failed: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!token) return;
    setTesting(true);
    try {
      const r = await testTelegram(token);
      toast.success(r.detail);
      onChange();
    } catch (e) {
      toast.error(`Telegram test failed: ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <CardContent className="p-4 space-y-4">
        <div>
          <h3 className="font-semibold text-lg flex items-center gap-2">
            <Send size={18} className="text-sky-500" />
            {t('integrations.telegram.title')}
            {isConfigured && (
              <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">
                {t('integrations.telegram.configured')}
              </Badge>
            )}
          </h3>
          <p className="text-sm text-muted-foreground mt-1">
            {t('integrations.telegram.description')}
          </p>
        </div>

        <div className="rounded-md border border-border bg-muted/30 p-4 text-sm text-muted-foreground space-y-2">
          <p>{t('integrations.telegram.howToGet')}</p>
          <ol className="list-decimal list-inside space-y-1 pl-1">
            <li>{t('integrations.telegram.step1')}</li>
            <li>{t('integrations.telegram.step2')}</li>
            <li>{t('integrations.telegram.step3')}</li>
          </ol>
        </div>

        <Field label={t('integrations.telegram.botToken')} required>
          <Input
            type="password"
            value={botToken}
            onChange={(e) => setBotToken(e.target.value)}
            placeholder={isConfigured ? '••••••••' : '1234567890:AAFm5j3tPy-SJ5P3rZ8KBmSTLLXfjmPI6bI'}
          />
        </Field>

        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={submitting || testing}>
            {submitting ? t('common.saving') : t('common.save')}
          </Button>
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={!isConfigured || submitting || testing}
            title={!isConfigured ? t('integrations.telegram.saveFirst') : ''}
          >
            {testing ? t('integrations.telegram.testing') : t('integrations.telegram.test')}
          </Button>
        </div>

        {summary?.last_test_at && (
          <p className="text-xs text-muted-foreground">
            {t('integrations.lastTest', {
              date: new Date(summary.last_test_at).toLocaleString('ru-RU'),
              status: summary.last_test_status ?? '',
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Helper ───────────────────────────────────────────────────────────────


function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm text-muted-foreground">
        {label}
        {required && <span className="text-destructive ml-0.5">*</span>}
      </span>
      {children}
    </label>
  );
}