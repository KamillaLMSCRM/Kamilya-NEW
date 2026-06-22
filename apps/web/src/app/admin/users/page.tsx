'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
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

  const handleCreate = async () => {
    const res = await fetch(`${API_URL}/v1/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(newUser),
    });
    if (res.ok) {
      setShowCreateModal(false);
      setNewUser({ email: '', first_name: '', last_name: '', role: 'student', password: '' });
      fetchUsers();
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
    const res = await api.post(`/v1/positions/${selectedPositionId}/assign/${assignModal.userId}`);
    if (res.status === 200 || res.status === 201) {
      const data = res.data;
      alert(`Должность назначена! Записано на ${data.courses_attached} курс(ов), новых записей: ${data.newly_enrolled}`);
      setAssignModal(null);
      setSelectedPositionId('');
      fetchUsers();
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
        <h1 className="text-2xl font-bold">Управление обучающимися</h1>
        <Button onClick={() => setShowCreateModal(true)}>Добавить обучающегося</Button>
      </div>

      <div className="flex gap-2">
        <Input
          placeholder="Поиск по имени или email..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="max-w-sm"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 text-gray-400">Загрузка...</div>
          ) : users.length === 0 ? (
            <div className="p-6 text-gray-400">Пользователей не найдено</div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th className="text-left p-3">Имя</th>
                  <th className="text-left p-3">Email</th>
                  <th className="text-left p-3">Роль</th>
                  <th className="text-left p-3">Должность</th>
                  <th className="text-left p-3">Статус</th>
                  <th className="text-left p-3">Создан</th>
                  <th className="text-right p-3">Действия</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} className="border-t">
                    <td className="p-3 font-medium">{user.first_name} {user.last_name}</td>
                    <td className="p-3 text-gray-500">{user.email}</td>
                    <td className="p-3">
                      <select
                        value={user.role}
                        onChange={(e) => handleChangeRole(user.id, e.target.value)}
                        className="border rounded px-2 py-1 text-sm"
                      >
                        <option value="student">Обучающийся</option>
                        <option value="instructor">Инструктор</option>
                        <option value="admin">Админ</option>
                        <option value="org_admin">Орг. админ</option>
                      </select>
                    </td>
                    <td className="p-3">
                      {getPositionName(user.position_id) ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                          {getPositionName(user.position_id)}
                        </span>
                      ) : (
                        <button
                          onClick={() => { setAssignModal({ userId: user.id, userName: `${user.first_name} ${user.last_name}`, currentPositionId: user.position_id }); setSelectedPositionId(user.position_id || ''); }}
                          className="text-xs text-warm-400 hover:text-primary transition-colors"
                        >
                          + Назначить
                        </button>
                      )}
                    </td>
                    <td className="p-3">
                      <Badge variant={user.is_active ? 'default' : 'destructive'}>
                        {user.is_active ? 'Активен' : 'Заблокирован'}
                      </Badge>
                    </td>
                    <td className="p-3 text-gray-500 text-sm">
                      {new Date(user.created_at).toLocaleDateString('ru')}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleToggleActive(user.id, user.is_active)}
                        className={`text-sm ${user.is_active ? 'text-red-500 hover:underline' : 'text-green-500 hover:underline'}`}
                      >
                        {user.is_active ? 'Заблокировать' : 'Разблокировать'}
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
        <span className="text-sm text-gray-500">Всего: {total} пользователей</span>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            Назад
          </Button>
          <span className="text-sm py-2 px-3">Стр. {page}</span>
          <Button variant="outline" onClick={() => setPage((p) => p + 1)} disabled={users.length < 20}>
            Далее
          </Button>
        </div>
      </div>

      {/* Create user modal */}
      <Modal open={showCreateModal} onOpenChange={setShowCreateModal}>
        <CardHeader>
          <CardTitle>Новый обучающийся</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="Email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} />
          <Input placeholder="Имя" value={newUser.first_name} onChange={(e) => setNewUser({ ...newUser, first_name: e.target.value })} />
          <Input placeholder="Фамилия" value={newUser.last_name} onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })} />
          <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })} className="w-full border rounded px-3 py-2">
            <option value="student">Обучающийся</option>
            <option value="instructor">Инструктор</option>
            <option value="admin">Админ</option>
          </select>
          <Input type="password" placeholder="Пароль (мин. 8 символов)" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
          <Button onClick={handleCreate} className="w-full">Создать</Button>
        </CardContent>
      </Modal>

      {/* Assign position modal */}
      {assignModal && (
        <Modal open={!!assignModal} onOpenChange={() => setAssignModal(null)}>
          <CardHeader>
            <CardTitle>Назначить должность: {assignModal.userName}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-warm-500">
              Обучающийся автоматически запишется на все курсы, привязанные к должности.
            </p>
            <select
              value={selectedPositionId}
              onChange={(e) => setSelectedPositionId(e.target.value)}
              className="w-full border rounded px-3 py-2"
            >
              <option value="">— Выберите должность —</option>
              {positions.map(p => (
                <option key={p.id} value={p.id}>{p.name}{p.department ? ` (${p.department})` : ''}</option>
              ))}
            </select>
            <Button onClick={handleAssignPosition} disabled={!selectedPositionId} className="w-full">
              Назначить и записать на курсы
            </Button>
          </CardContent>
        </Modal>
      )}
    </div>
  );
}
