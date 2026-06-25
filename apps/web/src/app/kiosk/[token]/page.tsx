'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button, Input } from '@/components/ui';
import { api } from '@/lib/api';

interface KioskInfo {
  name: string;
  tenant_name: string;
  scope_position_name: string | null;
  location: string | null;
  valid: boolean;
  reason_if_invalid: string | null;
}

interface KioskCourse {
  course_id: string;
  title: string;
  description: string;
  status: string;  // 'not_started' | 'in_progress' | 'completed'
}

interface KioskIdentifyResponse {
  user: {
    user_id: string;
    first_name: string;
    last_name: string;
    personnel_number: string;
    position_name: string | null;
  };
  kiosk_name: string;
  kiosk_location: string | null;
  courses: KioskCourse[];
}

const REASON_LABELS: Record<string, string> = {
  kiosk_not_found: 'Ссылка не найдена. Проверьте QR-код.',
  kiosk_disabled: 'Этот киоск отключён. Обратитесь к HR.',
  kiosk_expired: 'Срок действия киоска истёк. Обратитесь к HR.',
};

const STATUS_LABELS: Record<string, string> = {
  not_started: 'Не начат',
  in_progress: 'В процессе',
  completed: 'Пройден',
};

const STATUS_COLORS: Record<string, string> = {
  not_started: 'bg-warm-100 text-warm-500',
  in_progress: 'bg-amber-100 text-amber-700',
  completed: 'bg-emerald-100 text-emerald-700',
};

export default function KioskPage() {
  const params = useParams();
  const token = params?.token as string;

  const [kiosk, setKiosk] = useState<KioskInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const [personnelNumber, setPersonnelNumber] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const [result, setResult] = useState<KioskIdentifyResponse | null>(null);

  // Fetch kiosk info on mount
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    (async () => {
      try {
        const res = await api.get(`/v1/kiosks/${encodeURIComponent(token)}`);
        setKiosk(res.data);
      } catch (err: any) {
        setKiosk({
          name: '',
          tenant_name: '',
          scope_position_name: null,
          location: null,
          valid: false,
          reason_if_invalid: 'kiosk_not_found',
        });
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const handleIdentify = useCallback(async () => {
    setError('');
    if (!token) return;
    if (!personnelNumber.trim()) {
      setError('Введите табельный номер');
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post(`/v1/kiosks/${encodeURIComponent(token)}/identify`, {
        personnel_number: personnelNumber.trim(),
      });
      setResult(res.data);
      // Don't clear PN — worker might re-enter to verify (kiosk is shared device)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Не удалось идентифицировать';
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  }, [token, personnelNumber]);

  const handleBack = () => {
    setResult(null);
    setPersonnelNumber('');
    setError('');
  };

  // ── Render ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-warm-50">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!kiosk || !kiosk.valid) {
    const reason = kiosk?.reason_if_invalid || 'kiosk_not_found';
    const label = REASON_LABELS[reason] || 'Киоск недоступен';
    return (
      <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
        <Card className="max-w-md w-full">
          <CardContent className="pt-8 text-center space-y-4">
            <div className="text-5xl">⚠️</div>
            <h1 className="text-xl font-bold text-warm-800">Киоск недоступен</h1>
            <p className="text-sm text-warm-600">{label}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── After identify: show user's courses ──
  if (result) {
    return (
      <div className="min-h-screen bg-warm-50 p-4">
        <div className="max-w-2xl mx-auto space-y-4 py-6">
          {/* User header */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-2xl">
                  {result.user.first_name[0]}{result.user.last_name[0]}
                </div>
                <div className="flex-1">
                  <div className="text-xl font-bold text-warm-800">
                    {result.user.first_name} {result.user.last_name}
                  </div>
                  <div className="text-sm text-warm-500">
                    Табельный №: <span className="font-mono">{result.user.personnel_number}</span>
                    {result.user.position_name && (
                      <span className="ml-2">· {result.user.position_name}</span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleBack}
                  className="rounded-xl border border-warm-200 px-3 py-1.5 text-sm text-warm-500 hover:bg-warm-50"
                >
                  Сменить
                </button>
              </div>
            </CardContent>
          </Card>

          {/* Courses */}
          <Card>
            <CardHeader>
              <CardTitle>Назначенные курсы</CardTitle>
            </CardHeader>
            <CardContent>
              {result.courses.length === 0 ? (
                <p className="text-sm text-warm-500 text-center py-6">
                  Курсы не назначены. Обратитесь к HR.
                </p>
              ) : (
                <div className="space-y-2">
                  {result.courses.map((c) => (
                    <a
                      key={c.course_id}
                      href={`/courses/${c.course_id}`}
                      className="block rounded-lg border border-warm-200 p-3 hover:border-primary hover:bg-primary/5 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-warm-800">{c.title}</div>
                          {c.description && (
                            <div className="text-xs text-warm-500 mt-1 line-clamp-2">
                              {c.description}
                            </div>
                          )}
                        </div>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_COLORS[c.status] || STATUS_COLORS.not_started}`}>
                          {STATUS_LABELS[c.status] || c.status}
                        </span>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <p className="text-center text-xs text-warm-400">
            {result.kiosk_name} · {result.kiosk_location || 'общий киоск'}
          </p>
        </div>
      </div>
    );
  }

  // ── Default: identify screen ──
  return (
    <div className="min-h-screen flex items-center justify-center bg-warm-50 p-4">
      <Card className="max-w-md w-full">
        <CardHeader>
          <div className="text-center space-y-2">
            <div className="text-5xl">🏭</div>
            <CardTitle>{kiosk.name}</CardTitle>
            <div className="text-sm text-warm-500">
              {kiosk.tenant_name}
              {kiosk.location && <span className="block text-xs mt-0.5">{kiosk.location}</span>}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-center text-sm text-warm-600">
            Введите ваш <strong>табельный номер</strong> чтобы увидеть назначенные курсы.
            {kiosk.scope_position_name && (
              <span className="block text-xs text-amber-700 mt-1">
                Этот киоск только для должности: <strong>{kiosk.scope_position_name}</strong>
              </span>
            )}
          </p>

          <label className="block">
            <span className="block text-xs font-semibold text-warm-500 mb-1">Табельный номер</span>
            <Input
              value={personnelNumber}
              onChange={(e) => setPersonnelNumber(e.target.value)}
              placeholder="T-1042"
              autoFocus
              autoComplete="off"
              className="text-lg"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && personnelNumber.trim()) handleIdentify();
              }}
            />
          </label>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <Button
            onClick={handleIdentify}
            disabled={submitting || !personnelNumber.trim()}
            className="w-full"
          >
            {submitting ? 'Проверяю...' : 'Показать курсы'}
          </Button>

          <p className="text-xs text-warm-400 text-center">
            Киоск предназначен для общего пользования (планшет в цехе).
            Все входы регистрируются для аудита.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
