'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Button, Badge, Table, Input, Modal } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';

interface Position {
  id: string;
  name: string;
  department: string;
  level: string;
  employee_count: number;
  created_at: string;
}

export default function PositionsPage() {
  const { t } = useT();
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [department, setDepartment] = useState('');
  const [level, setLevel] = useState('');
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchPositions = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/positions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setPositions(data.items || data || []);
      }
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => {
    fetchPositions();
  }, [fetchPositions]);

  const handleCreate = async () => {
    if (!name.trim()) return;
    const res = await fetch(`${API_URL}/v1/positions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ name, department, level }),
    });
    if (res.ok) {
      setShowCreate(false);
      setName('');
      setDepartment('');
      setLevel('');
      fetchPositions();
    }
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Должности</h1>
        <Button onClick={() => setShowCreate(true)}>+ {t('common.create')}</Button>
      </div>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Новая должность">
        <div className="space-y-4">
          <Input
            placeholder="Название должности"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Input
            placeholder="Отдел"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          />
          <Input
            placeholder="Уровень (junior/middle/senior)"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          />
          <div className="flex gap-2 justify-end">
            <Button variant="outline" onClick={() => setShowCreate(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleCreate}>{t('common.create')}</Button>
          </div>
        </div>
      </Modal>

      {positions.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {t('common.none')}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <Table>
            <thead>
              <tr>
                <th className="text-left p-3">{t('courses.courseTitle')}</th>
                <th className="text-left p-3">Отдел</th>
                <th className="text-left p-3">Уровень</th>
                <th className="text-left p-3">Сотрудников</th>
                <th className="text-left p-3">Действия</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.id} className="border-t">
                  <td className="p-3 font-medium">{pos.name}</td>
                  <td className="p-3 text-gray-500">{pos.department}</td>
                  <td className="p-3">
                    <Badge variant="outline">{pos.level}</Badge>
                  </td>
                  <td className="p-3">{pos.employee_count}</td>
                  <td className="p-3">
                    <Button variant="outline" size="sm">Подробнее</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
