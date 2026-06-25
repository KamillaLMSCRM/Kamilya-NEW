'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface EmployeeNode {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
  assigned_courses: number;
  completed_courses: number;
  ready_percent: number;
}

interface PositionNode {
  id: string;
  name: string;
  department: string;
  employee_count: number;
  ready_percent: number;
  employees: EmployeeNode[];
}

interface DepartmentNode {
  name: string;
  position_count: number;
  employee_count: number;
  ready_percent: number;
  positions: PositionNode[];
}

interface TreeResponse {
  departments: DepartmentNode[];
  summary: {
    total_employees: number;
    total_departments: number;
    total_positions: number;
    overall_ready_percent: number;
    total_assigned_courses: number;
    total_completed_courses: number;
  };
}

const PROGRESS_COLORS = (pct: number) => {
  if (pct === 0) return 'bg-warm-100 text-warm-500';
  if (pct < 50) return 'bg-rose-100 text-rose-700';
  if (pct < 100) return 'bg-amber-100 text-amber-700';
  return 'bg-emerald-100 text-emerald-700';
};

function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-warm-100 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all ${
            percent === 0 ? 'bg-warm-200' :
            percent < 50 ? 'bg-rose-400' :
            percent < 100 ? 'bg-amber-400' :
            'bg-emerald-500'
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className={`text-xs font-semibold tabular-nums min-w-[36px] text-right ${PROGRESS_COLORS(percent)}`}>
        {percent}%
      </span>
    </div>
  );
}

export default function AdminEmployeesPage() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const [tree, setTree] = useState<TreeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  // Track which nodes are expanded (default: all expanded for first load)
  const [expandedDepts, setExpandedDepts] = useState<Set<string>>(new Set());
  const [expandedPositions, setExpandedPositions] = useState<Set<string>>(new Set());

  const fetchTree = useCallback(async () => {
    if (!accessToken) return;
    try {
      const res = await api.get('/v1/admin/staff/tree');
      setTree(res.data);
      // Expand all by default
      setExpandedDepts(new Set(res.data.departments.map((d: DepartmentNode) => d.name)));
      setExpandedPositions(new Set(
        res.data.departments.flatMap((d: DepartmentNode) => d.positions.map((p: PositionNode) => p.id))
      ));
    } catch (err: any) {
      toast.error('Не удалось загрузить структуру штата');
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const toggleDept = (name: string) => {
    setExpandedDepts(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const togglePos = (id: string) => {
    setExpandedPositions(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="p-6 max-w-6xl mx-auto">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!tree) return null;

  const { summary, departments } = tree;

  if (departments.length === 0) {
    return (
      <div className="p-6 max-w-6xl mx-auto space-y-6">
        <h1 className="text-2xl font-bold text-warm-800">📊 Структура штата</h1>
        <Card>
          <CardContent className="py-12 text-center text-warm-400">
            <div className="text-5xl mb-3">👥</div>
            <p className="text-sm">Сотрудников с должностями пока нет.</p>
            <p className="text-xs mt-1">Загрузите штатное расписание в <a href="/admin/staff" className="text-primary underline">/admin/staff</a></p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-warm-800">📊 Структура штата</h1>
          <p className="text-sm text-warm-500 mt-1">
            Прогресс обязательных курсов по отделам и должностям
          </p>
        </div>
        <button
          onClick={fetchTree}
          className="rounded-xl border border-warm-200 px-3 py-1.5 text-sm text-warm-600 hover:bg-warm-50"
        >
          🔄 Обновить
        </button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg bg-warm-50 p-3 text-center">
          <div className="text-2xl font-bold text-warm-800">{summary.total_employees}</div>
          <div className="text-xs text-warm-600">Сотрудников</div>
        </div>
        <div className="rounded-lg bg-warm-50 p-3 text-center">
          <div className="text-2xl font-bold text-warm-800">{summary.total_departments}</div>
          <div className="text-xs text-warm-600">Отделов</div>
        </div>
        <div className="rounded-lg bg-warm-50 p-3 text-center">
          <div className="text-2xl font-bold text-warm-800">{summary.total_positions}</div>
          <div className="text-xs text-warm-600">Должностей</div>
        </div>
        <div className="rounded-lg bg-warm-50 p-3 text-center">
          <div className={`text-2xl font-bold ${summary.overall_ready_percent === 100 ? 'text-emerald-700' : summary.overall_ready_percent < 50 ? 'text-rose-700' : 'text-amber-700'}`}>
            {summary.overall_ready_percent}%
          </div>
          <div className="text-xs text-warm-600">
            Готово ({summary.total_completed_courses} / {summary.total_assigned_courses})
          </div>
        </div>
      </div>

      {/* Tree */}
      <Card>
        <CardContent className="p-0">
          <div className="divide-y divide-warm-100">
            {departments.map((dept) => {
              const deptOpen = expandedDepts.has(dept.name);
              return (
                <div key={dept.name}>
                  {/* Department row */}
                  <button
                    type="button"
                    onClick={() => toggleDept(dept.name)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-warm-50 text-left"
                  >
                    <span className="text-warm-400 text-sm w-4">
                      {deptOpen ? '▼' : '▶'}
                    </span>
                    <span className="text-lg">🏢</span>
                    <span className="font-semibold text-warm-800">{dept.name}</span>
                    <span className="text-xs text-warm-500">
                      {dept.position_count} должностей · {dept.employee_count} чел
                    </span>
                    <div className="flex-1 max-w-xs ml-4">
                      <ProgressBar percent={dept.ready_percent} />
                    </div>
                  </button>

                  {/* Positions */}
                  {deptOpen && (
                    <div className="bg-warm-50/40">
                      {dept.positions.map((pos) => {
                        const posOpen = expandedPositions.has(pos.id);
                        return (
                          <div key={pos.id}>
                            <button
                              type="button"
                              onClick={() => togglePos(pos.id)}
                              className="w-full flex items-center gap-3 pl-10 pr-4 py-2.5 hover:bg-warm-50 text-left border-t border-warm-100"
                            >
                              <span className="text-warm-400 text-xs w-4">
                                {posOpen ? '▼' : '▶'}
                              </span>
                              <span className="text-base">👷</span>
                              <span className="font-medium text-warm-700 text-sm">{pos.name}</span>
                              <span className="text-xs text-warm-500">
                                {pos.employee_count} чел
                              </span>
                              <div className="flex-1 max-w-[180px] ml-2">
                                <ProgressBar percent={pos.ready_percent} />
                              </div>
                            </button>

                            {/* Employees */}
                            {posOpen && (
                              <div className="bg-white border-t border-warm-100">
                                {pos.employees.length === 0 ? (
                                  <div className="pl-16 pr-4 py-2 text-xs text-warm-400 italic">
                                    Нет сотрудников на этой должности
                                  </div>
                                ) : (
                                  pos.employees.map((emp) => (
                                    <div
                                      key={emp.id}
                                      className="flex items-center gap-3 pl-16 pr-4 py-2 border-t border-warm-50"
                                    >
                                      <span className="text-sm">👤</span>
                                      <span className="text-sm text-warm-800">
                                        {emp.full_name}
                                      </span>
                                      {emp.personnel_number && (
                                        <span className="text-[11px] font-mono text-warm-400">
                                          № {emp.personnel_number}
                                        </span>
                                      )}
                                      <span className="flex-1" />
                                      {emp.assigned_courses === 0 ? (
                                        <span className="text-[11px] text-warm-400 italic">
                                          курсы не назначены
                                        </span>
                                      ) : (
                                        <span className="text-[11px] text-warm-500 tabular-nums">
                                          {emp.completed_courses} / {emp.assigned_courses}
                                        </span>
                                      )}
                                      <div className="w-32">
                                        <ProgressBar percent={emp.ready_percent} />
                                      </div>
                                    </div>
                                  ))
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
