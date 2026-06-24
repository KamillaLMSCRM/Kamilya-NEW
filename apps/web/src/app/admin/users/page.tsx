'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  position_id: string | null;
  created_at: string;
  last_login: string | null;
}

interface Position {
  id: string;
  name: string;
  department: string;
}

export default function AdminUsersPage() {
  const { t } = useT();
  const [users, setUsers] = useState<User[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newUser, setNewUser] = useState({ email: '', first_name: '', last_name: '', role: 'student', password: '' });
  const [assignModal, setAssignModal] = useState<{ userId: string; userName: string; currentPositionId: string | null } | null>(null);
  const [selectedPositionId, setSelectedPositionId] = useState('');
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchUsers = useCallback(async () => {
    if (!token) return;
    const params = new URLSearchParams({ page: String(page), per_page: '20' });
    if (search) params.set('search', search);
    try {
      const res = await fetch(`${API_URL}/v1/users?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setUsers(data.users || []);
        setTotal(data.total || 0);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL, page, search]);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await api.get('/v1/positions');
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch {}
  }, []);

  useEffect(() => { fetchUsers(); fetchPositions(); }, [fetchUsers, fetchPositions]);

  const [createError, setCreateError] = useState('');

  const handleCreate = async () => {
    setCreateError('');
    if (!newUser.email.trim()) { setCreateError('Введите email'); return; }
    if (!newUser.first_name.trim()) { setCreateError('Введите имя'); return; }
    if (!newUser.last_name.trim()) { setCreateError('Введите фамилию'); return; }
    if (newUser.password.length < 8) { setCreateError('Пароль должен быть минимум 8 символов'); return; }

    const res = await fetch(`${API_URL}/v1/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(newUser),
    });
    if (res.ok) {
      setShowCreateModal(false);
      setNewUser({ email: '', first_name: '', last_name: '', role: 'student', password: '' });
      fetchUsers();
    } else {
      const err = await res.json().catch(() => ({ detail: 'Ошибка сервера' }));
      setCreateError(err.detail || 'Ошибка создания пользователя');
    }
  };

  const handleToggleActive = async (userId: string, currentActive: boolean) => {
    const method = currentActive ? 'DELETE' : 'PATCH';
    const res = await fetch(`${API_URL}/v1/users/${userId}`, {
      method,
      headers: { Authorization: `Bearer ${token}` },
      ...(method === 'PATCH' ? { body: JSON.stringify({ is_active: true }), headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } } : {}),
    });
    if (res.ok) fetchUsers();
  };

  const handleChangeRole = async (userId: string, newRole: string) => {
    const res = await fetch(`${API_URL}/v1/users/${userId}/role?role=${newRole}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) fetchUsers();
  };

  const handleAssignPosition = async () => {
    if (!assignModal || !selectedPositionId) return;
    try {
      const res = await api.post(`/v1/positions/${selectedPositionId}/assign/${assignModal.userId}`);
      if (res.status === 200 || res.status === 201) {
        const data = res.data as {
          position?: string;
          courses_attached?: number;
          newly_enrolled?: number;
          unenrolled_from_old?: number;
        };
        const parts: string[] = [];
        parts.push(t('toast.positionAssigned'));
        if (typeof data.newly_enrolled === 'number') {
          parts.push(`Новых записей: ${data.newly_enrolled}`);
        }
        if (typeof data.courses_attached === 'number') {
          parts.push(`Курсов: ${data.courses_attached}`);
        }
        if (data.unenrolled_from_old && data.unenrolled_from_old > 0) {
          parts.push(`Отменено записей со старой должности: ${data.unenrolled_from_old}`);
        }
        toast.success(parts.join(' · '));
        setAssignModal(null);
        setSelectedPositionId('');
        fetchUsers();
      }
    } catch (err: any) {
      toast.error(t('common.saveFailed'), {
        description: err?.response?.data?.detail || err?.message,
      });
    }
  };

  const getPositionName = (posId: string | null) => {
    if (!posId) return null;
    const pos = positions.find(p => p.id === posId);
    return pos?.name || null;
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-warm-800">{t('users.title')}</h1>
        <Button onClick={() => setShowCreateModal(true)}>{t('admin.addAdminUser')}</Button>
      </div>

      <div className="flex gap-2">
        <label htmlFor="users-search" className="sr-only">
          {t('users.searchPlaceholder')}
        </label>
        <Input
          id="users-search"
          placeholder={t('users.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="max-w-sm"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-warm-400">{t('users.loadingList')}</div>
          ) : users.length === 0 ? (
            <div className="p-6 text-warm-400">{t('users.noUsersFound')}</div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th scope="col" className="text-left p-3">{t('users.name')}</th>
                  <th scope="col" className="text-left p-3">{t('users.email')}</th>
                  <th scope="col" className="text-left p-3">{t('users.role')}</th>
                  <th scope="col" className="text-left p-3">{t('users.position')}</th>
                  <th scope="col" className="text-left p-3">{t('users.status')}</th>
                  <th scope="col" className="text-left p-3">{t('users.created')}</th>
                  <th scope="col" className="text-right p-3">{t('users.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} className="border-t">
                    <td className="p-3 font-medium">
                      {user.first_name} {user.last_name}
                    </td>
                    <td className="p-3 text-warm-500">{user.email}</td>
                    <td className="p-3">
                      <label htmlFor={`role-${user.id}`} className="sr-only">
                        {t('users.changeRole')}
                      </label>
                      <select
                        id={`role-${user.id}`}
                        value={user.role}
                        onChange={(e) => handleChangeRole(user.id, e.target.value)}
                        className="border rounded px-2 py-1 text-sm bg-white"
                      >
                        <option value="student">{t('users.roleStudent')}</option>
                        <option value="teacher">{t('users.roleTeacher')}</option>
                        <option value="org_admin">{t('users.roleOrgAdmin')}</option>
                        <option value="admin">{t('users.roleAdmin')}</option>
                        <option value="superadmin">{t('users.roleSuperadmin')}</option>
                      </select>
                    </td>
                    <td className="p-3">
                      {getPositionName(user.position_id) ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                          {getPositionName(user.position_id)}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setAssignModal({
                              userId: user.id,
                              userName: `${user.first_name} ${user.last_name}`,
                              currentPositionId: user.position_id,
                            });
                            setSelectedPositionId(user.position_id || '');
                          }}
                          className="text-xs text-warm-400 hover:text-primary transition-colors"
                        >
                          + {t('users.assignPosition')}
                        </button>
                      )}
                    </td>
                    <td className="p-3">
                      <Badge variant={user.is_active ? 'default' : 'destructive'}>
                        {user.is_active ? t('users.active') : t('users.blocked')}
                      </Badge>
                    </td>
                    <td className="p-3 text-warm-500 text-sm">
                      {new Date(user.created_at).toLocaleDateString(undefined)}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        type="button"
                        onClick={() => handleToggleActive(user.id, user.is_active)}
                        className={`text-sm hover:underline ${
                          user.is_active ? 'text-red-500' : 'text-emerald-500'
                        }`}
                      >
                        {user.is_active ? t('users.block') : t('users.unblock')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between items-center">
        <span className="text-sm text-warm-500">
          {t('users.totalCount', { total })}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            {t('users.prevPage')}
          </Button>
          <span className="text-sm py-2 px-3 text-warm-700">
            {t('users.page', { page })}
          </span>
          <Button
            variant="outline"
            onClick={() => setPage((p) => p + 1)}
            disabled={users.length < 20}
          >
            {t('users.nextPage')}
          </Button>
        </div>
      </div>

      {/* Create user modal */}
      <Modal open={showCreateModal} onOpenChange={setShowCreateModal}>
        <CardHeader>
          <CardTitle>{t('users.createTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="block">
            <span className="text-sm text-warm-700 mb-1 block">{t('users.email')}</span>
            <Input
              type="email"
              value={newUser.email}
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-warm-700 mb-1 block">{t('users.name')}</span>
            <Input
              value={newUser.first_name}
              onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-warm-700 mb-1 block">{t('users.surname')}</span>
            <Input
              value={newUser.last_name}
              onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-sm text-warm-700 mb-1 block">{t('users.role')}</span>
            <select
              value={newUser.role}
              onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
              className="w-full border border-warm-200 rounded-lg px-3 py-2 text-sm bg-white"
            >
              <option value="student">{t('users.roleStudent')}</option>
              <option value="teacher">{t('users.roleTeacher')}</option>
              <option value="org_admin">{t('users.roleOrgAdmin')}</option>
              <option value="admin">{t('users.roleAdmin')}</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-warm-700 mb-1 block">{t('users.password')}</span>
            <Input
              type="password"
              value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
            />
          </label>
          {createError && <p className="text-sm text-red-500">{createError}</p>}
          <Button onClick={handleCreate} className="w-full">
            {t('users.createButton')}
          </Button>
        </CardContent>
      </Modal>

      {/* Assign position modal */}
      {assignModal && (
        <Modal open={!!assignModal} onOpenChange={() => setAssignModal(null)}>
          <CardHeader>
            <CardTitle>
              {t('users.assignPosition')}: {assignModal.userName}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-warm-500">{t('users.assignPositionHint')}</p>
            <label className="block">
              <span className="sr-only">{t('users.position')}</span>
              <select
                value={selectedPositionId}
                onChange={(e) => setSelectedPositionId(e.target.value)}
                className="w-full border border-warm-200 rounded-lg px-3 py-2 text-sm bg-white"
              >
                <option value="">{t('users.selectPosition')}</option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.department ? ` (${p.department})` : ''}
                  </option>
                ))}
              </select>
            </label>
            <Button
              onClick={handleAssignPosition}
              disabled={!selectedPositionId}
              className="w-full"
            >
              {t('users.assignAndEnroll')}
            </Button>
          </CardContent>
        </Modal>
      )}
    </div>
  );
}
