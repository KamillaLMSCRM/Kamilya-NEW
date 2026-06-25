'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface KioskLink {
  id: string;
  name: string;
  token: string;
  kiosk_url: string;
  location: string | null;
  scope_position_id: string | null;
  scope_position_name: string | null;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}

interface Position {
  id: string;
  name: string;
  department: string;
}

export default function AdminKiosksPage() {
  const { t } = useT();
  const accessToken = useAuthStore((s) => s.accessToken);

  const [kiosks, setKiosks] = useState<KioskLink[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  // Form state
  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [scopePositionId, setScopePositionId] = useState<string>('');

  const fetchKiosks = useCallback(async () => {
    if (!accessToken) return;
    try {
      const res = await api.get('/v1/admin/kiosks');
      setKiosks(Array.isArray(res.data) ? res.data : []);
    } catch (err: any) {
      toast.error('Не удалось загрузить список киосков');
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await api.get('/v1/positions');
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch {}
  }, []);

  useEffect(() => {
    fetchKiosks();
    fetchPositions();
  }, [fetchKiosks, fetchPositions]);

  const resetForm = () => {
    setName('');
    setLocation('');
    setScopePositionId('');
    setCreateError('');
  };

  const handleCreate = async () => {
    setCreateError('');
    if (name.trim().length < 2) { setCreateError('Название должно быть минимум 2 символа'); return; }
    setCreating(true);
    try {
      const body: any = { name: name.trim() };
      if (location.trim()) body.location = location.trim();
      if (scopePositionId) body.scope_position_id = scopePositionId;
      await api.post('/v1/admin/kiosks', body);
      toast.success('Киоск создан');
      setShowCreate(false);
      resetForm();
      fetchKiosks();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Ошибка создания';
      setCreateError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setCreating(false);
    }
  };

  const handleToggleActive = async (kiosk: KioskLink) => {
    try {
      await api.patch(`/v1/admin/kiosks/${kiosk.id}`, { is_active: !kiosk.is_active });
      toast.success(kiosk.is_active ? 'Киоск отключён' : 'Киоск активирован');
      fetchKiosks();
    } catch (err: any) {
      toast.error('Не удалось изменить статус');
    }
  };

  const handleDelete = async (kiosk: KioskLink) => {
    if (!confirm(`Удалить киоск "${kiosk.name}"? Работники больше не смогут войти через эту ссылку.`)) return;
    try {
      await api.delete(`/v1/admin/kiosks/${kiosk.id}`);
      toast.success('Киоск удалён');
      fetchKiosks();
    } catch (err: any) {
      toast.error('Не удалось удалить');
    }
  };

  const copyKioskUrl = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success('Ссылка скопирована');
    } catch {
      toast.error('Не удалось скопировать');
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">🖥️ Киоски для цехов</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Создайте общую ссылку для киоска в цехе. Распечатайте QR-код и повесьте на стену —
            сотрудники вводят табельный номер и проходят назначенные курсы на общем устройстве.
          </p>
        </div>
        <Button onClick={() => { setShowCreate(true); resetForm(); }}>
          + Создать киоск
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-muted-foreground">Загрузка...</div>
          ) : kiosks.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <div className="text-4xl mb-2">🏭</div>
              <p>Киосков пока нет. Создайте первый для вашего цеха.</p>
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th className="text-left p-3">Название</th>
                  <th className="text-left p-3">Локация</th>
                  <th className="text-left p-3">Ограничение</th>
                  <th className="text-left p-3">Статус</th>
                  <th className="text-left p-3">Создан</th>
                  <th className="text-right p-3">Действия</th>
                </tr>
              </thead>
              <tbody>
                {kiosks.map((k) => (
                  <tr key={k.id} className="border-t">
                    <td className="p-3">
                      <div className="font-medium text-foreground">{k.name}</div>
                      <div className="flex items-center gap-1 mt-1">
                        <input
                          readOnly
                          value={k.kiosk_url}
                          onClick={(e) => (e.target as HTMLInputElement).select()}
                          className="flex-1 max-w-md rounded border border-border px-2 py-0.5 text-[10px] font-mono bg-muted"
                        />
                        <button
                          type="button"
                          onClick={() => copyKioskUrl(k.kiosk_url)}
                          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-muted"
                          title="Скопировать"
                        >
                          📋
                        </button>
                      </div>
                    </td>
                    <td className="p-3 text-muted-foreground text-sm">
                      {k.location || <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="p-3 text-sm">
                      {k.scope_position_name ? (
                        <Badge variant="outline">{k.scope_position_name}</Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">любая должность</span>
                      )}
                    </td>
                    <td className="p-3">
                      {k.is_active ? (
                        <Badge variant="default" className="bg-success/15 text-success">Активен</Badge>
                      ) : (
                        <Badge variant="outline">Отключён</Badge>
                      )}
                    </td>
                    <td className="p-3 text-muted-foreground text-xs">
                      {new Date(k.created_at).toLocaleDateString('ru-RU')}
                    </td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleToggleActive(k)}
                          className="text-xs px-2 py-1 rounded border border-border hover:bg-muted"
                        >
                          {k.is_active ? 'Отключить' : 'Включить'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(k)}
                          className="text-xs px-2 py-1 rounded border border-destructive/40 text-destructive hover:bg-destructive/10"
                        >
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {showCreate && (
        <Modal open={showCreate} onOpenChange={() => setShowCreate(false)}>
          <CardHeader>
            <CardTitle>🖥️ Новый киоск</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block">
              <span className="block text-xs font-semibold text-muted-foreground mb-1">Название *</span>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Кирпичный цех — ТБ инструктаж"
                autoFocus
              />
            </label>
            <label className="block">
              <span className="block text-xs font-semibold text-muted-foreground mb-1">Локация (опционально)</span>
              <Input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Цех №1, Алматы, ул. Промышленная 5"
              />
              <span className="block text-[11px] text-muted-foreground mt-1">
                Где физически стоит киоск (планшет). Для вашего учёта.
              </span>
            </label>
            <label className="block">
              <span className="block text-xs font-semibold text-muted-foreground mb-1">Ограничить по должности</span>
              <select
                value={scopePositionId}
                onChange={(e) => setScopePositionId(e.target.value)}
                className="w-full rounded-xl border border-border px-3 py-2 text-sm bg-card"
              >
                <option value="">Не ограничивать (любой сотрудник тенанта)</option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{p.department ? ` (${p.department})` : ''}
                  </option>
                ))}
              </select>
              <span className="block text-[11px] text-muted-foreground mt-1">
                Если выбрать должность — только сотрудники этой должности смогут войти на киоск.
                Оставьте пустым для общего киоска (ТБ инструктаж для всех).
              </span>
            </label>
            {createError && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">
                {createError}
              </div>
            )}
            <div className="flex gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowCreate(false)} className="flex-1">
                Отмена
              </Button>
              <Button onClick={handleCreate} disabled={creating} className="flex-1">
                {creating ? 'Создаю...' : 'Создать киоск'}
              </Button>
            </div>
          </CardContent>
        </Modal>
      )}
    </div>
  );
}
