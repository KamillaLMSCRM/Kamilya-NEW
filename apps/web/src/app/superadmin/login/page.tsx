'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, ShieldCheck, Loader2 } from 'lucide-react';

import { Logo } from '@/components/brand/Logo';
import { Button, Input } from '@/components/ui';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { clearStoredAuth } from '@/lib/auth';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useT } from '@/i18n/useT';

export default function SuperadminLoginPage() {
  const router = useRouter();
  const { t } = useT();
  const { login } = useAuthStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      clearStoredAuth();
      const res = await api.post('/v1/auth/superadmin-login', {
        email: email.trim(),
        password,
      });
      login(res.data.access_token, res.data.user);
      router.push('/admin/super');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || t('publicUi.superadminLogin.error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-gradient-to-b from-warning/5 to-background">
      <div className="absolute right-4 top-4">
        <LanguageSwitcher />
      </div>
      <main className="w-full max-w-md p-8">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <Logo variant="full" size={44} />
          </div>
          <div className="flex items-center justify-center gap-2 mt-2">
            <ShieldCheck className="w-5 h-5 text-warning" />
            <h2 className="text-xl font-semibold text-foreground">{t('publicUi.superadminLogin.title')}</h2>
          </div>
          <p className="text-sm text-muted-foreground mt-2">
            {t('publicUi.superadminLogin.subtitle')}
          </p>
        </div>

        {error && (
          <div
            className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm"
            role="alert"
          >
            {error}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          autoComplete="off"
          className="space-y-4 bg-card border border-border rounded-xl p-6 shadow-sm"
        >
          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              Email
            </label>
            <Input
              id="email"
              name="platform-operator-email"
              type="email"
              required
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-1">
              {t('publicUi.superadminLogin.password')}
            </label>
            <Input
              id="password"
              name="platform-operator-password"
              type="password"
              required
              minLength={8}
              autoComplete="off"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            variant="default"
            className="w-full"
            disabled={loading || !email || password.length < 8}
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {t('publicUi.superadminLogin.signingIn')}
              </>
            ) : (
              t('publicUi.superadminLogin.submit')
            )}
          </Button>
        </form>

        <div className="mt-6 text-center space-y-2">
          <p className="text-xs text-muted-foreground">
            {t('publicUi.superadminLogin.notice')}{' '}
            <Link href="/login" className="text-primary hover:underline">
              {t('publicUi.superadminLogin.tenantLogin')}
            </Link>
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('publicUi.superadminLogin.back')}
          </Link>
        </div>
      </main>
    </div>
  );
}
