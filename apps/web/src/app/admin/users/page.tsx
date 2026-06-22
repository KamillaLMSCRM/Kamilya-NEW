'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table, Modal, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';

interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newUser, setNewUser] = useState({ email: '', first_name: '', last_name: '', role: 'student', password: '' });
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

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleCreate = async () => {
    const res = await fetch(`${API_URL}/v1/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
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

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Управление пользователями</h1>
        <Button onClick={() => setShowCreateModal(true)}>Добавить пользователя</Button>
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

      <Modal open={showCreateModal} onOpenChange={setShowCreateModal}>
        <CardHeader>
          <CardTitle>Новый пользователь</CardTitle>
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
    </div>
  );
}
