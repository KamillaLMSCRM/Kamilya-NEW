'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Button, Input } from '@/components/ui';
import { Clock3, KeyRound, UserRound } from 'lucide-react';
import { PublicWorkspace, WorkspacePanel } from '@/features/workspace-design';
import { getPublicWorkspaceCopy } from '@/features/workspace-design/publicCopy';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';
import { setAuth, getStoredAuth, AuthState } from '@/lib/auth';
import { useIdleTimeout } from '@/lib/useIdleTimeout';

interface KioskInfo {
  name: string;
  tenant_name: string;
  scope_position_name: string | null;
  location: string | null;
  valid: boolean;
  reason_if_invalid: string | null;
}

interface KioskCourse {
  course_id: string;
  title: string;
  description: string;
  status: string;  // 'not_started' | 'in_progress' | 'completed'
}

interface KioskIdentifyResponse {
  user: {
    user_id: string;
    first_name: string;
    last_name: string;
    personnel_number: string;
    position_name: string | null;
  };
  kiosk_name: string;
  kiosk_location: string | null;
  courses: KioskCourse[];
  access_token: string;
  token_type: string;
}

const STATUS_COLORS: Record<string, string> = {
  not_started: 'bg-muted text-muted-foreground',
  in_progress: 'bg-warning/15 text-warning',
  completed: 'bg-success/15 text-success',
};

export default function KioskPage() {
  const params = useParams();
  const token = params?.token as string;
  const { lang } = useT();
  const copy = getPublicWorkspaceCopy(lang);
  const reasonLabels: Record<string, string> = { kiosk_not_found: copy.kioskMissing, kiosk_disabled: copy.kioskDisabled, kiosk_expired: copy.kioskExpired };
  const statusLabels: Record<string, string> = { not_started: copy.notStarted, in_progress: copy.inProgress, completed: copy.completed };

  const [kiosk, setKiosk] = useState<KioskInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const [personnelNumber, setPersonnelNumber] = useState('');
  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const [result, setResult] = useState<KioskIdentifyResponse | null>(null);
  const previousAuthRef = useRef<AuthState | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const leaveKioskSession = useCallback(() => {
    if (typeof window !== 'undefined') sessionStorage.removeItem('kamilya_kiosk_session');
    if (previousAuthRef.current) {
      setAuth(previousAuthRef.current.access_token, previousAuthRef.current.user);
    }
    previousAuthRef.current = null;
    setResult(null);
    setPersonnelNumber('');
    setPin('');
    setError('');
    setSessionExpired(true);
  }, []);

  const { warningSeconds } = useIdleTimeout({
    enabled: Boolean(result),
    onTimeout: leaveKioskSession,
  });

  // Fetch kiosk info on mount
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const res = await api.get(`/v1/kiosks/${encodeURIComponent(token)}`);
        setKiosk(res.data);
      } catch (err: any) {
        setKiosk({
          name: '',
          tenant_name: '',
          scope_position_name: null,
          location: null,
          valid: false,
          reason_if_invalid: 'kiosk_not_found',
        });
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const handleIdentify = useCallback(async () => {
    setError('');
    if (!token) return;
    if (!personnelNumber.trim() || !/^\d{6}$/.test(pin)) {
      setError(copy.identifyInvalid);
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post(`/v1/kiosks/${encodeURIComponent(token)}/identify`, {
        personnel_number: personnelNumber.trim(),
        pin,
      });
      setResult(res.data);
      previousAuthRef.current = getStoredAuth();
      setAuth(res.data.access_token, {
        user_id: res.data.user.user_id,
        tenant_id: null,
        tenant: null,
        telegram_id: '',
        role: 'student',
        full_name: `${res.data.user.first_name} ${res.data.user.last_name}`.trim(),
        email: null,
      });
      if (typeof window !== 'undefined') sessionStorage.setItem('kamilya_kiosk_session', '1');
      setSessionExpired(false);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || copy.identifyFailed;
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  }, [token, personnelNumber, pin, copy.identifyInvalid, copy.identifyFailed]);

  const handleBack = () => {
    if (typeof window !== 'undefined') sessionStorage.removeItem('kamilya_kiosk_session');
    if (previousAuthRef.current) {
      setAuth(previousAuthRef.current.access_token, previousAuthRef.current.user);
    }
    previousAuthRef.current = null;
    setResult(null);
    setPersonnelNumber('');
    setPin('');
    setError('');
    setSessionExpired(false);
  };

  // ── Render ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <PublicWorkspace id="kiosk-access" actions={<LanguageSwitcher />}><WorkspacePanel><div role="status" className="flex min-h-40 items-center justify-center gap-3 text-sm text-muted-foreground"><div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />{copy.loading}</div></WorkspacePanel></PublicWorkspace>
    );
  }

  if (!kiosk || !kiosk.valid) {
    const reason = kiosk?.reason_if_invalid || 'kiosk_not_found';
    const label = reasonLabels[reason] || copy.kioskUnavailable;
    return (
      <PublicWorkspace id="kiosk-access" title={copy.kioskUnavailable} icon={<KeyRound />} actions={<LanguageSwitcher />}><WorkspacePanel><p role="alert" className="text-sm leading-7 text-muted-foreground">{label}</p></WorkspacePanel></PublicWorkspace>
    );
  }

  if (sessionExpired && !result) {
    return (
      <PublicWorkspace id="kiosk-access" title={copy.sessionDone} description={copy.sessionDoneHint} icon={<Clock3 />} actions={<LanguageSwitcher />}><div className="mx-auto max-w-lg"><WorkspacePanel><Button className="min-h-11 w-full" onClick={() => setSessionExpired(false)}>{copy.returnLogin}</Button></WorkspacePanel></div></PublicWorkspace>
    );
  }

  // ── After identify: show user's courses ──
  if (result) {
    return (
      <PublicWorkspace id="kiosk-access" title={`${result.user.first_name} ${result.user.last_name}`} description={`${copy.personnel}: ${result.user.personnel_number}`} icon={<UserRound />} actions={<><LanguageSwitcher /><Button variant="outline" onClick={handleBack}>{copy.changePerson}</Button></>}>
          {warningSeconds !== null && (
            <div className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning" role="status">
              {copy.idleWarning.replace('{seconds}', String(warningSeconds))}
            </div>
          )}
        <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
          <WorkspacePanel title={result.kiosk_name} bodyClassName="space-y-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-xl font-semibold text-primary">{result.user.first_name[0]}{result.user.last_name[0]}</div>
            {result.user.position_name && <p className="text-sm font-medium">{result.user.position_name}</p>}
            <p className="text-sm leading-6 text-muted-foreground">{result.kiosk_location || copy.sharedKiosk}</p>
            <p className="border-t border-border pt-4 text-xs leading-6 text-muted-foreground">{copy.kioskAuditHint}</p>
          </WorkspacePanel>
          <WorkspacePanel title={copy.assignedCourses}>
              {result.courses.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  {copy.noKioskCourses}
                </p>
              ) : (
                <div className="grid min-w-0 gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))]">
                  {result.courses.map((c) => (
                    <Link
                      key={c.course_id}
                      href={`/courses/${c.course_id}`}
                      onClick={() => {
                        if (typeof window !== 'undefined') {
                          sessionStorage.setItem('kamilya_kiosk_session', '1');
                          sessionStorage.setItem('kamilya_kiosk_return', `/kiosk/${token}`);
                        }
                      }}
                      className="block min-w-0 rounded-xl border border-border p-4 transition-colors hover:border-primary/40 hover:bg-primary/5"
                    >
                      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-foreground">{c.title}</div>
                          {c.description && (
                            <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                              {c.description}
                            </div>
                          )}
                        </div>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_COLORS[c.status] || STATUS_COLORS.not_started}`}>
                          {statusLabels[c.status] || c.status}
                        </span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
          </WorkspacePanel>
        </div>
      </PublicWorkspace>
    );
  }

  // ── Default: identify screen ──
  return (
    <PublicWorkspace id="kiosk-access" title={kiosk.name} description={kiosk.tenant_name} icon={<KeyRound />} actions={<LanguageSwitcher />}>
      <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <WorkspacePanel title={copy.accessStep} bodyClassName="space-y-4">
          {kiosk.location && <p className="text-sm font-medium">{kiosk.location}</p>}
          <p className="text-sm leading-7 text-muted-foreground">{copy.identifyHint}
            {kiosk.scope_position_name && (
              <span className="block text-xs text-warning mt-1">
                {copy.kioskScope}: <strong>{kiosk.scope_position_name}</strong>
              </span>
            )}
          </p>
          <p className="border-t border-border pt-4 text-xs leading-6 text-muted-foreground">{copy.kioskAuditHint}</p>
        </WorkspacePanel>
        <WorkspacePanel title={copy.confirmationStep} bodyClassName="space-y-5">

          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">{copy.personnel}</span>
            <Input
              value={personnelNumber}
              onChange={(e) => setPersonnelNumber(e.target.value)}
              placeholder="T-1042"
              autoFocus
              autoComplete="off"
              className="text-lg"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && personnelNumber.trim()) handleIdentify();
              }}
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">{copy.kioskPin}</span>
            <Input
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder={copy.pinPlaceholder}
              inputMode="numeric"
              autoComplete="one-time-code"
              className="text-lg tracking-[0.35em]"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && personnelNumber.trim() && /^\d{6}$/.test(pin)) handleIdentify();
              }}
            />
          </label>

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button
            onClick={handleIdentify}
            disabled={submitting || !personnelNumber.trim() || !/^\d{6}$/.test(pin)}
            className="min-h-11 w-full"
          >
            {submitting ? copy.checking : copy.showCourses}
          </Button>

        </WorkspacePanel>
      </div>
    </PublicWorkspace>
  );
}
