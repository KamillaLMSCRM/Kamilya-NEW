'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface Position {
  id: string;
  name: string;
  department: string;
  level: string;
  responsibilities: string;
  requirements: string;
  course_ids: string[];
  employee_count: number;
  created_at: string;
  re_enrolled?: number;
}

interface Course {
  id: string;
  title: string;
  status: string;
}

export default function PositionsPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [positions, setPositions] = useState<Position[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editPos, setEditPos] = useState<Position | null>(null);
  const [name, setName] = useState('');
  const [department, setDepartment] = useState('');
  const [level, setLevel] = useState('');
  const [responsibilities, setResponsibilities] = useState('');
  const [requirements, setRequirements] = useState('');
  const [selectedCourseIds, setSelectedCourseIds] = useState<string[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await api.get('/v1/positions');
      setPositions(Array.isArray(res.data) ? res.data : []);
    } catch {} finally {
      setLoading(false);
    }
  }, []);

  const fetchCourses = useCallback(async () => {
    try {
      const res = await api.get('/v1/courses');
      setCourses(Array.isArray(res.data) ? res.data : []);
    } catch {}
  }, []);

  useEffect(() => { fetchPositions(); fetchCourses(); }, [fetchPositions, fetchCourses]);

  const resetForm = () => {
    setName(''); setDepartment(''); setLevel(''); setResponsibilities(''); setRequirements('');
    setSelectedCourseIds([]); setEditPos(null); setShowCreate(false);
  };

  const toggleCourse = (cid: string) => {
    setSelectedCourseIds(prev =>
      prev.includes(cid) ? prev.filter(id => id !== cid) : [...prev, cid]
    );
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    await api.post('/v1/positions', {
      name, department, level, responsibilities, requirements,
      course_ids: selectedCourseIds,
    });
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
    setSelectedCourseIds(pos.course_ids || []);
    setShowCreate(true);
  };

  const handleUpdate = async () => {
    if (!editPos) return;
    const res = await api.put(`/v1/positions/${editPos.id}`, {
      name, department, level, responsibilities, requirements,
      course_ids: selectedCourseIds,
    });
    const data = res.data as { re_enrolled?: number } | undefined;
    resetForm();
    fetchPositions();
    toast.success(t('toast.positionUpdated'));
    if (data?.re_enrolled && data.re_enrolled > 0) {
      toast.success(t('toast.positionReEnrolled', { count: data.re_enrolled }));
    } else {
      toast.success(t('toast.positionReEnrolledNone'));
    }
  };

  const handleDelete = async (id: string) => {
        const ok = await confirm({
      title: t('dialogs.confirmDeletePosition'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    await api.delete(`/v1/positions/${id}`);
    fetchPositions();
  };

  const handleAnalyzeJD = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAnalyzing(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = useAuthStore.getState().accessToken;
      const API_URL = process.env.NEXT_PUBLIC_API_URL;
      const res = await fetch(`${API_URL}/v1/positions/analyze-jd`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Ошибка анализа' }));
        toast.error(t('common.saveFailed'), { description: err.detail || 'Ошибка анализа' });
        return;
      }
      const data = await res.json();
      if (data.name) setName(data.name);
      if (data.department) setDepartment(data.department);
      if (data.level) setLevel(data.level);
      if (data.responsibilities) setResponsibilities(data.responsibilities);
      if (data.requirements) setRequirements(data.requirements);
      setShowCreate(true);
    } catch (err) {
      toast.error(t('common.saveFailed'), { description: 'Не удалось проанализировать файл' });
    } finally {
      setAnalyzing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-warm-800 font-display">Должности</h1>
        <div className="flex gap-2">
          <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc,.txt" onChange={handleAnalyzeJD} className="hidden" />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={analyzing}
            className="rounded-xl border border-warm-200 px-4 py-2.5 text-sm font-medium text-warm-600 hover:bg-warm-50 transition-colors disabled:opacity-50"
          >
            {analyzing ? 'Анализ...' : 'Загрузить JD'}
          </button>
          <button onClick={() => { resetForm(); setShowCreate(true); }} className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary/90 transition-colors">
            + Добавить должность
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={resetForm} />
          <div className="relative bg-white rounded-2xl shadow-card-lg w-full max-w-lg mx-4 p-6 z-10 max-h-[90vh] overflow-y-auto">
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
              <div>
                <label className="block text-xs font-semibold text-warm-500 mb-1">
                  Курсы должности <span className="text-warm-300 font-normal">(обучающиеся автоматически запишутся)</span>
                </label>
                {courses.length === 0 ? (
                  <p className="text-xs text-warm-400 py-2">Нет курсов. Создайте курс в разделе «Генерация курсов».</p>
                ) : (
                  <div className="space-y-1.5 max-h-40 overflow-y-auto border border-warm-200 rounded-xl p-2">
                    {courses.map(c => (
                      <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-warm-50 cursor-pointer text-sm">
                        <input
                          type="checkbox"
                          checked={selectedCourseIds.includes(c.id)}
                          onChange={() => toggleCourse(c.id)}
                          className="rounded border-warm-300 text-primary focus:ring-primary"
                        />
                        <span className="flex-1 truncate">{c.title}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${c.status === 'published' ? 'bg-emerald-50 text-emerald-600' : 'bg-warm-100 text-warm-500'}`}>
                          {c.status === 'published' ? 'Опубл.' : 'Черновик'}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
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
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-bold text-warm-800">{pos.name}</h3>
                    {pos.level && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">{pos.level}</span>}
                    {pos.course_ids.length > 0 && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">
                        {pos.course_ids.length} {pos.course_ids.length === 1 ? 'курс' : 'курса'}
                      </span>
                    )}
                    {pos.employee_count > 0 && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-600">
                        {pos.employee_count} обучающихся
                      </span>
                    )}
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
{dialog}
    </div>
  );
}
