'use client';

import { useState } from 'react';
import { Card, CardContent, Button, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

export default function SettingsPage() {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const [firstName, setFirstName] = useState(user?.firstName || '');
  const [lastName, setLastName] = useState(user?.lastName || '');
  const [email, setEmail] = useState(user?.email || '');
  const [saved, setSaved] = useState(false);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const handleSave = async () => {
    setSaved(false);
    try {
      await fetch(`${API_URL}/v1/users/me`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ first_name: firstName, last_name: lastName, email }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      console.error('Failed to save settings', e);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">{t('settings.title')}</h1>

      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold">{t('settings.profile')}</h2>
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">{t('auth.firstName')}</label>
            <Input
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">{t('auth.lastName')}</label>
            <Input
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-sm font-medium text-gray-700 mb-1 block">{t('auth.email')}</label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-4">
            <Button onClick={handleSave}>{t('common.save')}</Button>
            {saved && (
              <span className="text-green-600 text-sm">Настройки сохранены!</span>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold">{t('settings.security')}</h2>
          <div className="text-sm text-gray-600">
            <p>Telegram: {user?.telegramId || 'Не привязан'}</p>
            <p className="mt-2">Для смены пароля обратитесь к администратору.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6 space-y-4">
          <h2 className="text-lg font-semibold">{t('settings.language')}</h2>
          <div className="flex gap-3">
            <Button variant="default">{t('ai.languages.ru')}</Button>
            <Button variant="outline">{t('ai.languages.kk')}</Button>
            <Button variant="outline">{t('ai.languages.en')}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
