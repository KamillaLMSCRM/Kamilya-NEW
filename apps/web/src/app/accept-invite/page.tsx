'use client';

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BookOpen, Building2, Mail, ShieldCheck, UserRound } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';

import { Logo } from '@/components/brand/Logo';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { getRoleHome } from '@/lib/rolePolicy';
import { useAuthStore } from '@/store/authStore';

interface PublicInvitation {
  masked_email: string;
  tenant_name: string;
  role: string;
  first_name: string;
  last_name: string;
  position_name: string | null;
  course_titles: string[];
  expires_at: string;
  valid: boolean;
  reason_if_invalid: string | null;
}

const REASON_LABELS: Record<string, string> = {
  invitation_not_found: 'Приглашение не найдено. Проверьте ссылку или попросите методолога прислать новую.',
  already_accepted: 'Это приглашение уже принято. Войдите в систему по коду из email.',
  superseded: 'Приглашение заменено новым. Используйте последнюю полученную ссылку.',
  revoked: 'Приглашение отозвано. Обратитесь к методологу вашей организации.',
  expired: 'Срок действия приглашения истёк. Попросите методолога создать новое.',
};

function normalizeCode(value: string): string {
  return value.replace(/\D/g, '').slice(0, 6);
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <AcceptInviteForm />
    </Suspense>
  );
}

function AcceptInviteForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get('token');
  const { login, accessToken } = useAuthStore();

  const [invitation, setInvitation] = useState<PublicInvitation | null>(null);
  const [loadingInvitation, setLoadingInvitation] = useState(true);
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [showIdentityHelp, setShowIdentityHelp] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    if (accessToken) {
      router.replace(getRoleHome(useAuthStore.getState().user?.role));
    }
  }, [accessToken, router]);

  useEffect(() => {
    if (!retryAt) {
      setSecondsLeft(0);
      return;
    }
    const update = () => setSecondsLeft(Math.max(0, Math.ceil((retryAt - Date.now()) / 1000)));
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [retryAt]);

  useEffect(() => {
    if (!token) {
      setLoadingInvitation(false);
      return;
    }
    void (async () => {
      try {
        const response = await api.get(`/v1/invitations/${encodeURIComponent(token)}`);
        setInvitation(response.data);
      } catch {
        setInvitation({
          masked_email: '',
          tenant_name: '',
          role: '',
          first_name: '',
          last_name: '',
          position_name: null,
          course_titles: [],
          expires_at: new Date().toISOString(),
          valid: false,
          reason_if_invalid: 'invitation_not_found',
        });
      } finally {
        setLoadingInvitation(false);
      }
    })();
  }, [token]);

  const fullName = useMemo(
    () => `${invitation?.first_name || ''} ${invitation?.last_name || ''}`.trim(),
    [invitation?.first_name, invitation?.last_name],
  );

  const requestCode = useCallback(async () => {
    if (!token || submitting || secondsLeft > 0) return;
    setError('');
    setSubmitting(true);
    try {
      const response = await api.post(
        `/v1/invitations/${encodeURIComponent(token)}/request-code`,
      );
      const retryAfter = Number(response.data.retry_after || 60);
      setRetryAt(Date.now() + retryAfter * 1000);
      setCodeSent(true);
    } catch (requestError: any) {
      setError(requestError?.response?.data?.detail || 'Не удалось отправить код. Попробуйте позже.');
    } finally {
      setSubmitting(false);
    }
  }, [secondsLeft, submitting, token]);

  const verifyCode = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || submitting) return;
    if (code.length !== 6) {
      setError('Введите шестизначный код из письма.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const response = await api.post(
        `/v1/invitations/${encodeURIComponent(token)}/accept`,
        { code },
      );
      login(response.data.access_token, response.data.user);
      router.replace(response.data.next_url || getRoleHome(response.data.role));
    } catch (verifyError: any) {
      setError(verifyError?.response?.data?.detail || 'Код неверный или истёк.');
    } finally {
      setSubmitting(false);
    }
  }, [code, login, router, submitting, token]);

  if (loadingInvitation) return <LoadingState />;
  if (!token) {
    return (
      <UnavailableState
        title="Ссылка неполная"
        message="Откройте полную ссылку из приглашения. В ней должен быть защищённый токен доступа."
      />
    );
  }
  if (!invitation?.valid) {
    const reason = invitation?.reason_if_invalid || 'invitation_not_found';
    return (
      <UnavailableState
        title="Приглашение недоступно"
        message={REASON_LABELS[reason] || 'Обратитесь к методологу вашей организации.'}
      />
    );
  }

  return (
    <div className="min-h-screen bg-muted/30 px-4 py-8 sm:py-12">
      <main className="mx-auto w-full max-w-xl">
        <div className="mb-6 flex justify-center">
          <Logo variant="full" size={40} />
        </div>

        <Card className="overflow-hidden border-border shadow-card">
          <CardHeader className="border-b bg-card px-5 py-5 sm:px-7">
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-md bg-primary/10 text-primary">
              <ShieldCheck className="h-6 w-6" aria-hidden="true" />
            </div>
            <CardTitle className="text-2xl">Вас пригласили пройти обучение</CardTitle>
            <p className="text-sm text-muted-foreground">
              Проверьте данные и подтвердите доступ кодом из рабочей почты.
            </p>
          </CardHeader>

          <CardContent className="space-y-6 px-5 py-6 sm:px-7">
            <section className="space-y-4 rounded-md border bg-muted/20 p-4" aria-label="Данные приглашения">
              <div className="flex items-start gap-3">
                <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
                <div>
                  <p className="text-xs text-muted-foreground">Организация</p>
                  <p className="font-semibold text-foreground">{invitation.tenant_name}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <UserRound className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
                <div>
                  <p className="text-xs text-muted-foreground">Сотрудник</p>
                  <p className="font-semibold text-foreground">{fullName}</p>
                  {invitation.position_name && (
                    <p className="text-sm text-muted-foreground">{invitation.position_name}</p>
                  )}
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Mail className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
                <div>
                  <p className="text-xs text-muted-foreground">Email для подтверждения</p>
                  <p className="font-medium text-foreground">{invitation.masked_email}</p>
                </div>
              </div>
            </section>

            {invitation.course_titles.length > 0 && (
              <section aria-labelledby="assigned-training-title">
                <div className="mb-2 flex items-center gap-2">
                  <BookOpen className="h-5 w-5 text-primary" aria-hidden="true" />
                  <h2 id="assigned-training-title" className="font-semibold">Назначенное обучение</h2>
                </div>
                <ul className="space-y-2">
                  {invitation.course_titles.map((title) => (
                    <li key={title} className="rounded-md border px-3 py-2 text-sm text-foreground">
                      {title}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {!codeSent ? (
              <Button className="h-11 w-full" onClick={requestCode} disabled={submitting}>
                <Mail className="h-4 w-4" aria-hidden="true" />
                {submitting ? 'Отправляем код...' : 'Получить код'}
              </Button>
            ) : (
              <form className="space-y-4" onSubmit={verifyCode}>
                <div>
                  <label htmlFor="invitation-code" className="mb-1.5 block text-sm font-medium">
                    Код из письма
                  </label>
                  <Input
                    id="invitation-code"
                    value={code}
                    onChange={(event) => setCode(normalizeCode(event.target.value))}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="000000"
                    aria-describedby="invitation-code-hint"
                    className="h-12 text-center text-xl tracking-[0.3em]"
                    autoFocus
                  />
                  <p id="invitation-code-hint" className="mt-1.5 text-xs text-muted-foreground">
                    Код действует 5 минут и подтверждает доступ к указанному email.
                  </p>
                </div>
                <Button type="submit" className="h-11 w-full" disabled={submitting || code.length !== 6}>
                  <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  {submitting ? 'Проверяем...' : 'Подтвердить и начать обучение'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={requestCode}
                  disabled={submitting || secondsLeft > 0}
                >
                  {secondsLeft > 0 ? `Отправить повторно через ${secondsLeft} с` : 'Отправить код повторно'}
                </Button>
              </form>
            )}

            {error && (
              <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="border-t pt-4">
              <button
                type="button"
                className="text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                onClick={() => setShowIdentityHelp((current) => !current)}
                aria-expanded={showIdentityHelp}
              >
                Данные или email указаны неверно
              </button>
              {showIdentityHelp && (
                <div className="mt-3 flex gap-2 rounded-md bg-warning/10 p-3 text-sm text-foreground">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                  <p>
                    Не продолжайте активацию. Попросите методолога исправить карточку сотрудника
                    и создать новое приглашение.
                  </p>
                </div>
              )}
            </div>

            <p className="text-center text-xs text-muted-foreground">
              Приглашение действует до{' '}
              {new Date(invitation.expires_at).toLocaleString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </p>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-label="Загрузка" />
    </div>
  );
}

function UnavailableState({ title, message }: { title: string; message: string }) {
  const router = useRouter();
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md">
        <CardContent className="space-y-4 p-6 text-center">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-md bg-warning/10 text-warning">
            <AlertTriangle className="h-6 w-6" aria-hidden="true" />
          </div>
          <h1 className="text-xl font-semibold">{title}</h1>
          <p className="text-sm text-muted-foreground">{message}</p>
          <Button variant="outline" className="w-full" onClick={() => router.push('/login')}>
            Перейти на страницу входа
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
