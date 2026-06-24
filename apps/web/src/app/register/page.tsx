'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Input, Button } from '@/components/ui';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';

export default function RegisterPage() {
  const router = useRouter();
  const { t } = useT();
  const [company, setCompany] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/v1/identity/auth/public-register`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            company,
            first_name: firstName,
            last_name: lastName,
            email,
            password,
          }),
        }
      );

      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: t('errors.serverError') }));
        throw new Error(data.detail || t('errors.serverError'));
      }

      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message);
      toast.error(t('errors.serverError'), { description: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white py-12">
      <main
        id="main-content"
        tabIndex={-1}
        className="w-full max-w-md p-8 bg-white rounded-xl shadow-md focus:outline-none"
      >
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-blue-600">Kamilya LMS</h1>
          <h2 className="text-xl font-semibold mt-2">{t('auth.register')}</h2>
        </div>

        {error && (
          <div
            className="mb-4 p-3 bg-red-50 text-red-600 rounded-lg text-sm"
            role="alert"
            aria-live="assertive"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate aria-describedby="register-form-help">
          <p id="register-form-help" className="sr-only">
            {t('a11y.formRequired') || 'All fields marked required must be filled.'}
          </p>
          <div>
            <label htmlFor="register-company" className="block text-sm font-medium mb-1">
              {t('auth.company') || 'Компания'}
              <span aria-hidden="true" className="text-red-500 ml-0.5">*</span>
            </label>
            <Input
              id="register-company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
              aria-required="true"
              autoComplete="organization"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="register-first-name" className="block text-sm font-medium mb-1">
                {t('auth.firstName')}
                <span aria-hidden="true" className="text-red-500 ml-0.5">*</span>
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
                {t('auth.lastName')}
                <span aria-hidden="true" className="text-red-500 ml-0.5">*</span>
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
            <label htmlFor="register-email" className="block text-sm font-medium mb-1">
              {t('auth.email')}
              <span aria-hidden="true" className="text-red-500 ml-0.5">*</span>
            </label>
            <Input
              id="register-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              aria-required="true"
              autoComplete="email"
            />
          </div>
          <div>
            <label htmlFor="register-password" className="block text-sm font-medium mb-1">
              {t('auth.passwordMin')}
              <span aria-hidden="true" className="text-red-500 ml-0.5">*</span>
            </label>
            <Input
              id="register-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-required="true"
              aria-describedby="register-password-hint"
              minLength={8}
              autoComplete="new-password"
            />
            <p id="register-password-hint" className="text-xs text-gray-500 mt-1">
              {t('auth.passwordMinHint') || 'Минимум 8 символов'}
            </p>
          </div>
          <Button type="submit" className="w-full" disabled={loading} aria-busy={loading}>
            {loading ? t('common.saving' as any) : t('auth.registerButton')}
          </Button>
        </form>

        <div className="mt-6 text-center text-sm text-gray-600">
          {t('auth.hasAccount')}{' '}
          <Link href="/login" className="text-blue-600 hover:underline">
            {t('auth.login')}
          </Link>
        </div>
      </main>
    </div>
  );
}
