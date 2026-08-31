'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent, Button, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useLanguageStore } from '@/store/languageStore';
import { locales, localeNames, type Locale } from '@/i18n/config';
import { api } from '@/lib/api';
import { CheckCircle2 } from 'lucide-react';
import { toast } from '@/components/ui/Toast';
import { PRODUCT_VERSION } from '@/lib/productVersion';

export default function ProfilePage() {
  const { t } = useT();
  const lang = useLanguageStore((state) => state.lang);
  const setLang = useLanguageStore((state) => state.setLang);
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const updatesLocale = lang === 'kk' ? 'kk' : 'ru';

  useEffect(() => {
    let cancelled = false;
    async function loadProfile() {
      try {
        const response = await api.get('/v1/users/me');
        if (cancelled) return;
        setFirstName(response.data.first_name || '');
        setLastName(response.data.last_name || '');
        setEmail(response.data.email || '');
      } catch (error: any) {
        toast.error(t('settings.loadError'), {
          description: error?.response?.data?.detail || error?.message,
        });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [t]);

  async function saveProfile() {
    setSaving(true);
    try {
      const response = await api.patch('/v1/users/me', {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
      });
      if (user) {
        setUser({
          ...user,
          full_name: `${response.data.first_name || ''} ${response.data.last_name || ''}`.trim() || user.email || '',
          email: response.data.email ?? user.email,
        });
      }
      toast.success(t('settings.saved'));
    } catch (error: any) {
      toast.error(t('settings.saveError'), {
        description: error?.response?.data?.detail || error?.message,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground font-display">{t('nav.myProfile')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{user?.tenant?.name || ''}</p>
      </div>

      <Card>
        <CardContent className="space-y-4 p-6">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.profile')}</h2>
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              {t('common.loading')}
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="profile-first-name" className="mb-1 block text-sm font-medium text-foreground">
                  {t('auth.firstName')}
                </label>
                <Input id="profile-first-name" value={firstName} onChange={(event) => setFirstName(event.target.value)} />
              </div>
              <div>
                <label htmlFor="profile-last-name" className="mb-1 block text-sm font-medium text-foreground">
                  {t('auth.lastName')}
                </label>
                <Input id="profile-last-name" value={lastName} onChange={(event) => setLastName(event.target.value)} />
              </div>
              <div>
                <label htmlFor="profile-email" className="mb-1 block text-sm font-medium text-foreground">
                  {t('auth.email')}
                </label>
                <Input id="profile-email" type="email" value={email} readOnly className="bg-muted" />
                <p className="mt-1 text-xs text-muted-foreground">{t('settings.emailLocked')}</p>
              </div>
              <Button onClick={() => void saveProfile()} disabled={saving}>
                {saving ? t('common.loading') : t('common.save')}
              </Button>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 p-6">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.language')}</h2>
          <p className="text-sm text-muted-foreground">{t('settings.languageHelp')}</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t('settings.language')}>
            {locales.map((locale: Locale) => {
              const active = lang === locale;
              return (
                <button
                  key={locale}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    setLang(locale);
                    toast.success(t('settings.languageChanged', { lang: localeNames[locale] }));
                  }}
                  className={'flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors ' +
                    (active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-foreground hover:border-primary/50')}
                >
                  {active && <CheckCircle2 className="mr-1.5 inline h-4 w-4" aria-hidden="true" />}
                  {localeNames[locale]}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-6">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.security')}</h2>
          <p className="text-sm text-foreground">
            <span className="font-medium">{t('settings.telegram')}:</span>{' '}
            {user?.telegram_id || t('settings.notLinked')}
          </p>
          <p className="text-sm text-muted-foreground">{t('settings.passwordHelp')}</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-foreground">{t('settings.about')}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t('settings.productVersion')}</p>
            </div>
            <span className="rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-sm font-semibold text-primary">
              Kamilya LMS {PRODUCT_VERSION}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.releaseNotesHelp')}</p>
          <a
            href={`https://www.kml.kz/${updatesLocale}/updates`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex text-sm font-semibold text-primary underline-offset-4 hover:underline"
          >
            {t('settings.whatsNew')}
          </a>
        </CardContent>
      </Card>
    </div>
  );
}
