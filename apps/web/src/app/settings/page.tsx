'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, Button, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useLanguageStore } from '@/store/languageStore';
import { locales, localeNames, type Locale } from '@/i18n/config';
import { api } from '@/lib/api';
import { CheckCircle2 } from 'lucide-react';
import { toast } from '@/components/ui/Toast';

export default function SettingsPage() {
  const { t } = useT();
  const lang = useLanguageStore((s) => s.lang);
  const setLang = useLanguageStore((s) => s.setLang);

  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.accessToken);

  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  // Load current profile from /users/me
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await api.get('/v1/users/me');
        if (cancelled) return;
        const data = res.data;
        setFirstName(data.first_name || '');
        setLastName(data.last_name || '');
        setEmail(data.email || '');
      } catch (err: any) {
        toast.error(t('settings.loadError'), {
          description: err?.response?.data?.detail || err?.message,
        });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.patch('/v1/users/me', {
        first_name: firstName,
        last_name: lastName,
        email: email || null,
      });
      toast.success(t('settings.saved'));
      // Refresh user store so TopBar reflects the new name
      const refreshed = await api.get('/v1/users/me');
      const { setStoredAuth, getStoredAuth } = await import('@/lib/auth');
      const current = getStoredAuth();
      if (current && refreshed.data) {
        setStoredAuth({
          ...current,
          user: {
            ...current.user,
            full_name: `${refreshed.data.first_name} ${refreshed.data.last_name}`.trim(),
            email: refreshed.data.email ?? current.user.email,
          },
        });
      }
    } catch (err: any) {
      toast.error(t('settings.saveError'), {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold text-foreground font-display">{t('settings.title')}</h1>

      {/* Profile */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.profile')}</h2>
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              {t('common.loading')}
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="settings-first-name" className="text-sm font-medium text-foreground mb-1 block">
                  {t('auth.firstName')}
                </label>
                <Input
                  id="settings-first-name"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="settings-last-name" className="text-sm font-medium text-foreground mb-1 block">
                  {t('auth.lastName')}
                </label>
                <Input
                  id="settings-last-name"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="settings-email" className="text-sm font-medium text-foreground mb-1 block">
                  {t('auth.email')}
                </label>
                <Input
                  id="settings-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? t('common.loading') : t('common.save')}
              </Button>
            </>
          )}
        </CardContent>
      </Card>

      {/* Language */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.language')}</h2>
          <p className="text-sm text-muted-foreground">{t('settings.languageHelp')}</p>
          <div className="flex gap-2" role="radiogroup" aria-label={t('settings.language')}>
            {locales.map((l) => {
              const active = lang === l;
              return (
                <button
                  key={l}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    setLang(l);
                    const msg = (() => {
                      if (l === 'ru') return 'Язык изменён: Русский';
                      if (l === 'kk') return 'Тіл өзгертілді: Қазақша';
                      return 'Language changed: English';
                    })();
                    toast.success(msg);
                  }}
                  className={
                    'flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors ' +
                    (active
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-card text-foreground hover:border-border')
                  }
                >
                  {active && <CheckCircle2 className="inline w-4 h-4 mr-1.5" aria-hidden="true" />}
                  {localeNames[l]}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold text-foreground">{t('settings.security')}</h2>
          <div className="text-sm text-foreground space-y-1">
            <p>
              <span className="font-medium">{t('settings.telegram')}:</span>{' '}
              {user?.telegram_id || t('settings.notLinked')}
            </p>
            <p className="text-muted-foreground">{t('settings.passwordHelp')}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
