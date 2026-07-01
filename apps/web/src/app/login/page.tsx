'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ChevronRight, Copy, Mail, MessageCircle, RefreshCw } from 'lucide-react';

import SkipLink from '@/components/SkipLink';
import { Logo } from '@/components/brand/Logo';
import { Button, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

type LoginMode = 'email' | 'telegram';

function getRoleHome(role?: string | null) {
  return role === 'student' ? '/student' : '/dashboard';
}

export default function LoginPage() {
  const router = useRouter();
  const { login, accessToken } = useAuthStore();
  const [mode, setMode] = useState<LoginMode>('email');
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [emailCodeSent, setEmailCodeSent] = useState(false);
  const [telegramCode, setTelegramCode] = useState('');
  const [expiresAt, setExpiresAt] = useState(0);
  const [timeLeft, setTimeLeft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (accessToken) {
      router.push(getRoleHome(useAuthStore.getState().user?.role));
    }
  }, [accessToken, router]);

  useEffect(() => {
    if (!expiresAt) return;
    const timer = setInterval(() => {
      const remaining = Math.max(0, expiresAt - Date.now() / 1000);
      if (remaining <= 0) {
        setTimeLeft('Код истек');
        if (pollingRef.current) clearInterval(pollingRef.current);
        return;
      }
      const minutes = Math.floor(remaining / 60);
      const seconds = Math.floor(remaining % 60);
      setTimeLeft(`${minutes}:${seconds.toString().padStart(2, '0')}`);
    }, 1000);
    return () => clearInterval(timer);
  }, [expiresAt]);

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  const startTelegramPolling = useCallback((authCode: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      try {
        const res = await api.post('/v1/auth/check-code', { code: authCode });
        if (res.data.verified && res.data.access_token) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          login(res.data.access_token, res.data.user);
          router.push(getRoleHome(res.data.user?.role));
        }
      } catch (err: any) {
        if (err.response?.status === 429) {
          setError('Слишком много запросов. Подождите минуту или обновите страницу.');
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      }
    }, 5000);
  }, [login, router]);

  async function requestEmailCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail || !normalizedEmail.includes('@')) {
      setError('Введите рабочий email.');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/v1/auth/email/request-code', { email: normalizedEmail });
      setEmail(normalizedEmail);
      setEmailCodeSent(true);
      setExpiresAt(Date.now() / 1000 + (res.data.expires_in || 300));
      toast.success('Код отправлен', { description: 'Если email есть в системе, письмо придет в течение минуты.' });
    } catch (err: any) {
      const message = err?.response?.data?.detail || 'Не удалось отправить код.';
      setError(message);
      toast.error('Ошибка входа', { description: message });
    } finally {
      setLoading(false);
    }
  }

  async function verifyEmailCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    const normalizedCode = emailCode.trim();
    if (normalizedCode.length !== 6) {
      setError('Введите 6-значный код из письма.');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/v1/auth/email/verify-code', {
        email: email.trim().toLowerCase(),
        code: normalizedCode,
      });
      login(res.data.access_token, res.data.user);
      router.push(getRoleHome(res.data.user?.role));
    } catch (err: any) {
      const message = err?.response?.data?.detail || 'Код неверный или истек.';
      setError(message);
      toast.error('Ошибка входа', { description: message });
    } finally {
      setLoading(false);
    }
  }

  async function generateTelegramCode() {
    setLoading(true);
    setError('');
    try {
      const res = await api.post('/v1/auth/generate-code');
      setTelegramCode(res.data.code);
      setExpiresAt(Date.now() / 1000 + res.data.expires_in);
      startTelegramPolling(res.data.code);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Ошибка генерации кода.');
    } finally {
      setLoading(false);
    }
  }

  async function copyTelegramCode() {
    if (!telegramCode) return;
    await navigator.clipboard.writeText(telegramCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function switchMode(nextMode: LoginMode) {
    setMode(nextMode);
    setError('');
    if (pollingRef.current) clearInterval(pollingRef.current);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-primary/5 to-background px-4 py-10">
      <SkipLink />
      <main id="main-content" className="w-full max-w-md rounded-lg bg-card p-8 shadow-card">
        <div className="mb-7 text-center">
          <div className="mb-3 flex justify-center">
            <Logo variant="full" size={40} />
          </div>
          <h1 className="text-xl font-semibold">Вход в Kamilya LMS</h1>
        </div>

        <div className="mb-5 grid grid-cols-2 rounded-md border border-input bg-muted p-1">
          <button
            type="button"
            onClick={() => switchMode('email')}
            className={`inline-flex h-10 items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors ${
              mode === 'email' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Mail className="h-4 w-4" aria-hidden="true" />
            Email
          </button>
          <button
            type="button"
            onClick={() => switchMode('telegram')}
            className={`inline-flex h-10 items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors ${
              mode === 'telegram' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <MessageCircle className="h-4 w-4" aria-hidden="true" />
            Telegram
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
            {error}
          </div>
        )}

        {mode === 'email' ? (
          <div className="space-y-5">
            {!emailCodeSent ? (
              <form onSubmit={requestEmailCode} className="space-y-4">
                <div>
                  <label htmlFor="email-login" className="mb-1 block text-sm font-medium">
                    Рабочий email
                  </label>
                  <Input
                    id="email-login"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="email"
                    placeholder="hr@company.kz"
                    required
                  />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? 'Отправляем...' : 'Получить код'}
                </Button>
              </form>
            ) : (
              <form onSubmit={verifyEmailCode} className="space-y-4">
                <div>
                  <label htmlFor="email-code" className="mb-1 block text-sm font-medium">
                    Код из письма
                  </label>
                  <Input
                    id="email-code"
                    value={emailCode}
                    onChange={(event) => setEmailCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                    inputMode="numeric"
                    placeholder="123456"
                    autoComplete="one-time-code"
                    required
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    Отправили код на {email}. Действует: {timeLeft || '5:00'}.
                  </p>
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? 'Проверяем...' : 'Войти'}
                </Button>
                <button
                  type="button"
                  onClick={() => {
                    setEmailCodeSent(false);
                    setEmailCode('');
                    setExpiresAt(0);
                  }}
                  className="w-full text-sm text-muted-foreground hover:text-foreground underline"
                >
                  Изменить email
                </button>
              </form>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {!telegramCode ? (
              <Button type="button" className="w-full" onClick={generateTelegramCode} disabled={loading}>
                {loading ? 'Генерируем...' : 'Получить Telegram-код'}
              </Button>
            ) : (
              <>
                <div className="text-center">
                  <p className="mb-3 text-sm text-muted-foreground">Ваш код для входа:</p>
                  <div className="flex justify-center gap-2" role="img" aria-label={`Код: ${telegramCode}`}>
                    {telegramCode.split('').map((digit, index) => (
                      <div
                        key={`${digit}-${index}`}
                        className="flex h-14 w-12 items-center justify-center rounded-md border-2 border-primary/20 bg-primary/10 font-mono text-2xl font-bold text-primary"
                      >
                        {digit}
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={copyTelegramCode}
                    className="mt-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary"
                  >
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    {copied ? 'Скопировано' : 'Скопировать код'}
                  </button>
                </div>

                <div className="text-center text-sm text-muted-foreground">
                  Код действителен: <span className="font-medium">{timeLeft}</span>
                </div>

                <div className="text-center">
                  <a
                    href="https://t.me/kamilla_lms_bot"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    <MessageCircle className="h-5 w-5" aria-hidden="true" />
                    Открыть бота
                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  </a>
                </div>

                <button
                  type="button"
                  onClick={generateTelegramCode}
                  className="flex w-full items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground underline"
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  Получить новый код
                </button>
              </>
            )}
          </div>
        )}

        <div className="mt-6 space-y-3 text-center text-sm text-muted-foreground">
          <Link href="/register-tenant" className="text-primary hover:underline">
            Зарегистрировать компанию
          </Link>
          <div>
            <Link
              href="/login/demo"
              className="inline-flex items-center gap-1.5 rounded-md bg-muted px-4 py-2 text-sm font-medium text-foreground hover:bg-muted"
            >
              Попробовать демо
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
