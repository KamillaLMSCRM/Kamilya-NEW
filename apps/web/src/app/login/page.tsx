'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { api } from '@/lib/api';
import SkipLink from '@/components/SkipLink';
import { useT } from '@/i18n/useT';
import { ChevronRight } from 'lucide-react';

export default function LoginPage() {
  const { t } = useT();
  const router = useRouter();
  const { login, accessToken } = useAuthStore();
  const [code, setCode] = useState('');
  const [expiresIn, setExpiresIn] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeLeft, setTimeLeft] = useState('');
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Redirect if already logged in
  useEffect(() => {
    if (accessToken) {
      router.push('/dashboard');
    }
  }, [accessToken, router]);

  // Generate code on mount
  useEffect(() => {
    generateCode();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  // Countdown timer
  useEffect(() => {
    if (!expiresIn) return;
    const timer = setInterval(() => {
      const now = Date.now() / 1000;
      const remaining = Math.max(0, expiresIn - now);
      if (remaining <= 0) {
        setTimeLeft('Код истёк');
        if (pollingRef.current) clearInterval(pollingRef.current);
      } else {
        const mins = Math.floor(remaining / 60);
        const secs = Math.floor(remaining % 60);
        setTimeLeft(`${mins}:${secs.toString().padStart(2, '0')}`);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [expiresIn]);

  const [copied, setCopied] = useState(false);

  const copyCode = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const generateCode = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.post('/v1/auth/generate-code');
      setCode(res.data.code);
      setExpiresIn(Date.now() / 1000 + res.data.expires_in);
      startPolling(res.data.code);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка генерации кода');
    } finally {
      setLoading(false);
    }
  };

  const startPolling = useCallback((authCode: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      try {
        const res = await api.post('/v1/auth/check-code', { code: authCode });
        if (res.data.verified && res.data.access_token) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          login(res.data.access_token, res.data.user);
          router.push('/dashboard');
        }
      } catch (err: any) {
        if (err.response?.status === 429) {
          setError('Слишком много запросов. Подождите 1 минуту или обновите страницу.');
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      }
    }, 5000);
  }, [login, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white">
      <SkipLink />
      <main id="main-content" className="w-full max-w-md p-8 bg-white rounded-xl shadow-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-blue-600">Kamilya LMS</h1>
          <h2 className="text-xl font-semibold mt-2">{t('auth.loginWithTelegram')}</h2>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm" role="alert">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-4 text-gray-600">{t('common.loading')}</p>
          </div>
        ) : code ? (
          <div className="space-y-6">
            {/* Code display */}
            <div className="text-center">
              <p className="text-sm text-gray-600 mb-3">Ваш код для входа:</p>
              <div className="flex justify-center gap-2" role="img" aria-label={`Код: ${code}`}>
                {code.split('').map((digit, i) => (
                  <div
                    key={i}
                    className="w-12 h-14 border-2 border-blue-200 rounded-lg flex items-center justify-center text-2xl font-mono font-bold text-blue-600 bg-blue-50"
                  >
                    {digit}
                  </div>
                ))}
              </div>
              <button
                onClick={copyCode}
                className="mt-3 inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-blue-600 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  {copied ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  )}
                </svg>
                {copied ? 'Скопировано!' : 'Копировать код'}
              </button>
            </div>

            {/* Timer */}
            <div className="text-center">
              <span className="text-sm text-gray-500">
                Код действителен: <span className="font-medium">{timeLeft}</span>
              </span>
            </div>

            {/* Bot link */}
            <div className="text-center">
              <p className="text-sm text-gray-600 mb-2">
                Откройте Telegram и отправьте код боту:
              </p>
              <a
                href="https://t.me/kamilla_lms_bot"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
                </svg>
                Открыть бота <ChevronRight className="w-4 h-4" />
              </a>
            </div>

            {/* Instructions */}
            <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
              <p className="font-medium mb-2">Как войти:</p>
              <ol className="list-decimal list-inside space-y-1">
                <li>Нажмите &laquo;Открыть бота&raquo;</li>
                <li>Отправьте 6-значный код боту</li>
                <li>Дождитесь подтверждения</li>
              </ol>
            </div>

            {/* Refresh button */}
            <button
              onClick={generateCode}
              className="w-full text-sm text-gray-500 hover:text-gray-700 underline"
            >
              Получить новый код
            </button>
          </div>
        ) : null}

        <div className="mt-6 text-center text-sm text-gray-600 space-y-2">
          <a href="/register" className="text-blue-600 hover:underline">
            {t('auth.register')}
          </a>
          <div>
            <a href="/login/demo" className="inline-flex items-center gap-1.5 px-4 py-2 bg-warm-100 text-warm-600 rounded-lg hover:bg-warm-200 transition-colors text-sm font-medium">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Попробовать
            </a>
          </div>
        </div>
      </main>
    </div>
  );
}
