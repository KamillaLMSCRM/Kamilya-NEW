'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Input, Button } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { Logo } from '@/components/brand/Logo';
import { api } from '@/lib/api';

type Step = 'form' | 'success';

export default function RegisterPage() {
  const router = useRouter();
  const { t } = useT();
  const [step, setStep] = useState<Step>('form');
  const [company, setCompany] = useState('');
  const [telegramId, setTelegramId] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [createdTenant, setCreatedTenant] = useState<{ slug: string; name: string } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validate telegram_id is a positive integer
    const tid = parseInt(telegramId.replace(/\s/g, ''), 10);
    if (!Number.isFinite(tid) || tid <= 0) {
      setError('Telegram ID должен быть положительным числом');
      return;
    }

    setLoading(true);
    try {
      const res = await api.post('/v1/auth/register-by-telegram', {
        company: company.trim(),
        telegram_id: tid,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      });

      setCreatedTenant({ slug: res.data.tenant_slug, name: res.data.tenant_name });
      setStep('success');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      // Structured error from backend: {code, message}
      const msg =
        (typeof detail === 'object' && detail?.message) ||
        (typeof detail === 'string' && detail) ||
        err?.message ||
        t('errors.serverError');
      setError(msg);
      toast.error(t('errors.serverError'), { description: msg });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-primary/5 to-background py-12">
      <main
        id="main-content"
        tabIndex={-1}
        className="w-full max-w-md p-8 bg-card rounded-xl shadow-card focus:outline-none"
      >
        <div className="text-center mb-8">
          <div className="flex justify-center mb-3">
            <Logo variant="full" size={40} />
          </div>
          <h2 className="text-xl font-semibold mt-2">
            {step === 'form' ? t('auth.register') : 'Готово!'}
          </h2>
          {step === 'form' && (
            <p className="text-sm text-muted-foreground mt-2">
              Создайте организацию Kamilya LMS
            </p>
          )}
        </div>

        {step === 'form' ? (
          <>
            {error && (
              <div
                className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm"
                role="alert"
                aria-live="assertive"
              >
                {error}
              </div>
            )}

            <form
              onSubmit={handleSubmit}
              className="space-y-4"
              noValidate
              aria-describedby="register-form-help"
            >
              <p id="register-form-help" className="sr-only">
                Все обязательные поля должны быть заполнены.
              </p>

              <div>
                <label htmlFor="register-company" className="block text-sm font-medium mb-1">
                  Название компании
                  <span aria-hidden="true" className="text-destructive ml-0.5">*</span>
                </label>
                <Input
                  id="register-company"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  required
                  aria-required="true"
                  autoComplete="organization"
                  placeholder="ТОО Acme Meat"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="register-first-name" className="block text-sm font-medium mb-1">
                    Имя
                    <span aria-hidden="true" className="text-destructive ml-0.5">*</span>
                  </label>
                  <Input
                    id="register-first-name"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    required
                    aria-required="true"
                    autoComplete="given-name"
                  />
                </div>
                <div>
                  <label htmlFor="register-last-name" className="block text-sm font-medium mb-1">
                    Фамилия
                    <span aria-hidden="true" className="text-destructive ml-0.5">*</span>
                  </label>
                  <Input
                    id="register-last-name"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    required
                    aria-required="true"
                    autoComplete="family-name"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="register-telegram-id" className="block text-sm font-medium mb-1">
                  Ваш Telegram ID
                  <span aria-hidden="true" className="text-destructive ml-0.5">*</span>
                </label>
                <Input
                  id="register-telegram-id"
                  type="number"
                  inputMode="numeric"
                  value={telegramId}
                  onChange={(e) => setTelegramId(e.target.value)}
                  required
                  aria-required="true"
                  aria-describedby="register-tg-hint"
                  placeholder="123456789"
                  min={1}
                />
                <p id="register-tg-hint" className="text-xs text-muted-foreground mt-1">
                  Откройте бота{' '}
                  <a
                    href="https://t.me/userinfobot"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    @userinfobot
                  </a>{' '}
                  в Telegram — он сразу пришлёт ваш ID.
                </p>
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={loading}
                aria-busy={loading}
              >
                {loading ? 'Создаём…' : 'Создать организацию'}
              </Button>
            </form>

            <div className="mt-6 text-center text-sm text-muted-foreground">
              Уже есть аккаунт?{' '}
              <Link href="/login" className="text-primary hover:underline">
                Войти
              </Link>
            </div>
          </>
        ) : (
          <>
            <div className="text-center space-y-4">
              <div className="mx-auto w-12 h-12 rounded-full bg-success/15 text-success flex items-center justify-center">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>

              <p className="text-sm text-foreground">
                Организация{' '}
                <strong>{createdTenant?.name}</strong> создана.
                <br />
                Вы назначены её администратором.
              </p>

              <div className="rounded-xl bg-muted p-4 text-left text-sm space-y-2">
                <p className="font-medium text-foreground">Что дальше:</p>
                <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                  <li>Откройте Telegram и запустите бота{' '}
                    <a
                      href="https://t.me/kamilla_lms_bot"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline"
                    >
                      @kamilla_lms_bot
                    </a>
                  </li>
                  <li>Нажмите &laquo;Войти&raquo; ниже — получите 6-значный код</li>
                  <li>Отправьте этот код боту — он подтвердит вход</li>
                </ol>
              </div>

              <Button
                type="button"
                className="w-full"
                onClick={() => router.push('/login')}
              >
                Войти через Telegram
              </Button>

              <button
                type="button"
                onClick={() => {
                  setStep('form');
                  setCreatedTenant(null);
                  setError('');
                }}
                className="text-xs text-muted-foreground hover:text-foreground underline"
              >
                Зарегистрировать другую организацию
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}