'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { api } from '@/lib/api';

interface Position {
  id: string;
  name: string;
  department: string;
  level: string;
  responsibilities: string;
  requirements: string;
  course_id: string | null;
  employee_count: number;
  created_at: string;
}

export default function PositionsPage() {
  const { t } = useT();
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editPos, setEditPos] = useState<Position | null>(null);
  const [name, setName] = useState('');
  const [department, setDepartment] = useState('');
  const [level, setLevel] = useState('');
  const [responsibilities, setResponsibilities] = useState('');
  const [requirements, setRequirements] = useState('');

  const fetchPositions = useCallback(async () => {
    try {
      const res = await api.get('/v1/positions');
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch {} finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPositions(); }, [fetchPositions]);

  const resetForm = () => {
    setName(''); setDepartment(''); setLevel(''); setResponsibilities(''); setRequirements('');
    setEditPos(null); setShowCreate(false);
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    await api.post('/v1/positions', { name, department, level, responsibilities, requirements });
    resetForm();
    fetchPositions();
  };

  const handleEdit = (pos: Position) => {
    setEditPos(pos);
    setName(pos.name);
    setDepartment(pos.department);
    setLevel(pos.level);
    setResponsibilities(pos.responsibilities);
    setRequirements(pos.requirements);
    setShowCreate(true);
  };

  const handleUpdate = async () => {
    if (!editPos) return;
    await api.put(`/v1/positions/${editPos.id}`, { name, department, level, responsibilities, requirements });
    resetForm();
    fetchPositions();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Удалить должность?')) return;
    await api.delete(`/v1/positions/${id}`);
    fetchPositions();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-warm-800 font-display">Должности</h1>
        <button onClick={() => { resetForm(); setShowCreate(true); }} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
          + Добавить должность
        </button>
      </div>

      {/* Create/Edit modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={resetForm} />
          <div className="relative bg-white rounded-2xl shadow-card-lg w-full max-w-lg mx-4 p-6 z-10">
            <h2 className="text-lg font-bold text-warm-800 font-display mb-4">
              {editPos ? 'Редактировать должность' : 'Новая должность'}
            </h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">Название *</label>
                <input value={name} onChange={e => setName(e.target.value)} placeholder="Frontend Developer" className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-warm-500 mb-1">Отдел</label>
                  <input value={department} onChange={e => setDepartment(e.target.value)} placeholder="IT" className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-warm-500 mb-1">Уровень</label>
                  <input value={level} onChange={e => setLevel(e.target.value)} placeholder="middle" className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">Обязанности</label>
                <textarea value={responsibilities} onChange={e => setResponsibilities(e.target.value)} rows={3} placeholder="Что должен делать на этой позиции..." className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">Требования</label>
                <textarea value={requirements} onChange={e => setRequirements(e.target.value)} rows={3} placeholder="Какие знания/навыки нужны..." className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm outline-none focus:border-primary transition-colors resize-none" />
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={resetForm} className="rounded-xl border border-warm-200 px-4 py-2 text-sm text-warm-500 hover:bg-warm-50 transition-colors">Отмена</button>
              <button onClick={editPos ? handleUpdate : handleCreate} className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
                {editPos ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : positions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-warm-200 py-12 text-center text-sm text-warm-400">
          Нет должностей. Добавьте первую.
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map((pos) => (
            <div key={pos.id} className="rounded-2xl border border-warm-100 bg-white p-5 shadow-card hover:shadow-card-hover transition-all">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-warm-800">{pos.name}</h3>
                    {pos.level && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">{pos.level}</span>}
                    {pos.course_id && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">Курс создан</span>}
                  </div>
                  {pos.department && <p className="text-sm text-warm-400 mt-1">{pos.department}</p>}
                  {pos.responsibilities && <p className="text-sm text-warm-500 mt-2 line-clamp-2">{pos.responsibilities}</p>}
                  {pos.requirements && <p className="text-xs text-warm-400 mt-1 line-clamp-1">Требования: {pos.requirements}</p>}
                </div>
                <div className="flex gap-2 ml-4">
                  <button onClick={() => handleEdit(pos)} className="rounded-xl border border-warm-200 px-3 py-1.5 text-xs text-warm-500 hover:border-warm-300 hover:text-warm-700 transition-colors">Изменить</button>
                  <button onClick={() => handleDelete(pos.id)} className="rounded-xl border border-red-200 px-3 py-1.5 text-xs text-red-400 hover:border-red-300 hover:text-red-600 transition-colors">Удалить</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
