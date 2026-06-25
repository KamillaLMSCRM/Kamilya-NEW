'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { setStoredAuth } from '@/lib/auth';
import { api } from '@/lib/api';

interface PublicInvitation {
  email: string;
  tenant_name: string;
  role: string;
  expires_at: string;
  valid: boolean;
  reason_if_invalid: string | null;
  requires_personnel_number: boolean;
}

const REASON_LABELS: Record<string, string> = {
  invitation_not_found: 'Приглашение не найдено. Проверьте ссылку или попросите методолога прислать новую.',
  already_accepted: 'Это приглашение уже принято. Войдите в систему.',
  superseded: 'Приглашение заменено новым. Проверьте, нет ли более свежей ссылки.',
  revoked: 'Приглашение отозвано. Свяжитесь с методологом.',
  expired: 'Срок действия приглашения истёк. Попросите методолога прислать новое.',
};

const ROLE_LABELS: Record<string, string> = {
  student: 'Студент',
  teacher: 'Преподаватель',
  admin: 'Администратор',
  org_admin: 'Админ организации',
};

export default function AcceptInvitePage() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get('token');

  const { login, accessToken } = useAuthStore();

  const [invitation, setInvitation] = useState<PublicInvitation | null>(null);
  const [loadingInvitation, setLoadingInvitation] = useState(true);

  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [personnelNumber, setPersonnelNumber] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Redirect if already logged in (defensive — shouldn't happen on this page)
  useEffect(() => {
    if (accessToken) router.push('/dashboard');
  }, [accessToken, router]);

  // Fetch invitation details on mount
  useEffect(() => {
    if (!token) {
      setLoadingInvitation(false);
      return;
    }
    (async () => {
      try {
        const res = await api.get(`/v1/invitations/${encodeURIComponent(token)}`);
        setInvitation(res.data);
      } catch (err: any) {
        setInvitation({
          email: '',
          tenant_name: '',
          role: '',
          expires_at: new Date().toISOString(),
          valid: false,
          reason_if_invalid: 'invitation_not_found',
          requires_personnel_number: false,
        });
      } finally {
        setLoadingInvitation(false);
      }
    })();
  }, [token]);

  const handleSubmit = useCallback(async () => {
    setError('');
    if (!token) { setError('Ссылка не содержит токен'); return; }
    if (firstName.trim().length < 1) { setError('Введите имя'); return; }
    if (lastName.trim().length < 1) { setError('Введите фамилию'); return; }
    if (invitation?.requires_personnel_number && !personnelNumber.trim()) {
      setError('Введите табельный номер — это требует HR для безопасности');
      return;
    }
    if (password.length < 8) { setError('Пароль должен быть минимум 8 символов'); return; }
    if (password !== password2) { setError('Пароли не совпадают'); return; }

    setSubmitting(true);
    try {
      const res = await api.post(`/v1/invitations/${encodeURIComponent(token)}/accept`, {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        password,
        ...(invitation?.requires_personnel_number
          ? { personnel_number: personnelNumber.trim() }
          : {}),
      });
      const { access_token, user_id, tenant_id, role } = res.data;

      // Fetch user profile to build AuthUser shape
      try {
        const meRes = await api.get('/v1/users/me');
        const me = meRes.data;
        const authUser = {
          user_id,
          tenant_id,
          telegram_id: me.telegram_id ? String(me.telegram_id) : '',
          role,
          full_name: `${me.first_name || ''} ${me.last_name || ''}`.trim() || `${firstName} ${lastName}`,
          email: me.email || invitation?.email || null,
        };
        login(access_token, authUser);
      } catch {
        // Fallback: store what we have
        const fallbackUser = {
          user_id,
          tenant_id,
          telegram_id: '',
          role,
          full_name: `${firstName} ${lastName}`,
          email: invitation?.email || null,
        };
        login(access_token, fallbackUser);
      }

      router.push('/dashboard');
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось принять приглашение';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  }, [token, firstName, lastName, password, password2, invitation, login, router]);

  // ── Render ──────────────────────────────────────────────────────────

  if (loadingInvitation) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
        <Card className="max-w-md w-full">
          <CardContent className="pt-6 text-center space-y-3">
            <div className="text-5xl">🔗</div>
            <h1 className="text-xl font-bold text-warm-800">Ссылка неполная</h1>
            <p className="text-sm text-warm-500">
              Откройте ссылку из приглашения целиком — она должна содержать токен после <code className="bg-warm-100 px-1 rounded">?token=...</code>
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!invitation || !invitation.valid) {
    const reason = invitation?.reason_if_invalid || 'invitation_not_found';
    const label = REASON_LABELS[reason] || 'Приглашение недоступно';
    return (
      <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
        <Card className="max-w-md w-full">
          <CardContent className="pt-6 text-center space-y-3">
            <div className="text-5xl">⚠️</div>
            <h1 className="text-xl font-bold text-warm-800">Приглашение недоступно</h1>
            <p className="text-sm text-warm-600">{label}</p>
            <Button
              variant="outline"
              onClick={() => router.push('/login')}
              className="w-full"
            >
              На страницу входа
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
      <Card className="max-w-md w-full">
        <CardHeader>
          <CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-2xl">🎉</span>
              <span>Добро пожаловать в {invitation.tenant_name}</span>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
            <div className="flex items-center gap-2 text-emerald-800">
              <span>✉️</span>
              <span className="font-semibold">{invitation.email}</span>
            </div>
            <div className="text-emerald-700 mt-1 text-xs">
              Роль: {ROLE_LABELS[invitation.role] || invitation.role} ·
              {' '}Ссылка действует до{' '}
              {new Date(invitation.expires_at).toLocaleDateString('ru-RU', {
                day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
              })}
            </div>
          </div>

          <p className="text-sm text-warm-600">
            Заполните имя, фамилию и задайте пароль — и вы в системе.
          </p>

          <label className="block">
            <span className="block text-xs font-semibold text-warm-500 mb-1">Имя</span>
            <Input
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="Иван"
              autoFocus
            />
          </label>
          <label className="block">
            <span className="block text-xs font-semibold text-warm-500 mb-1">Фамилия</span>
            <Input
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Иванов"
            />
          </label>
          {invitation?.requires_personnel_number && (
            <label className="block">
              <span className="block text-xs font-semibold text-warm-500 mb-1">
                Табельный номер <span className="text-red-500">*</span>
              </span>
              <Input
                value={personnelNumber}
                onChange={(e) => setPersonnelNumber(e.target.value)}
                placeholder="T-1042"
                autoComplete="off"
              />
              <span className="block text-[11px] text-warm-500 mt-1">
                HR указал табельный номер для этого приглашения. Введите его для подтверждения.
              </span>
            </label>
          )}
          <label className="block">
            <span className="block text-xs font-semibold text-warm-500 mb-1">Пароль (минимум 8 символов)</span>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
            />
          </label>
          <label className="block">
            <span className="block text-xs font-semibold text-warm-500 mb-1">Повторите пароль</span>
            <Input
              type="password"
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
            />
          </label>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <Button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full"
          >
            {submitting ? 'Создаём аккаунт...' : 'Войти в систему'}
          </Button>

          <p className="text-xs text-warm-400 text-center">
            Принимая приглашение, вы соглашаетесь с правилами использования платформы.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
