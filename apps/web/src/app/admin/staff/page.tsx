'use client';

import { useState, useRef, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { ApplyRulesProgress } from '@/components/ui/ApplyRulesProgress';
import RulesTab from './_tabs/RulesTab';
import CompanyCoursesTab from './_tabs/CompanyCoursesTab';

interface PreviewItem {
  row_number: number;
  personnel_number: string;
  first_name: string;
  last_name: string;
  department: string;
  position: string;
  email: string | null;
  phone: string | null;
  action: string;  // 'create' | 'update' | 'skip'
  existing_user_id: string | null;
  notes: string[];
}

interface PreviewResponse {
  items: PreviewItem[];
  new_positions: string[];
  new_departments: string[];
  summary: { create: number; update: number; skip: number; new_positions: number; new_departments: number; invalid_rows?: number };
  invalid_rows: Array<{ row_number: number; errors: string[]; raw: Record<string, string> }>;
  missing_required_columns: string[];
  total_rows_in_file: number;
}

const ACTION_LABELS: Record<string, string> = {
  create: 'Создать',
  update: 'Обновить',
  skip: 'Без изменений',
};

const ACTION_COLORS: Record<string, string> = {
  create: 'bg-success/15 text-success',
  update: 'bg-warning/15 text-warning',
  skip: 'bg-muted text-muted-foreground',
};

export default function AdminStaffPage() {
  const { t } = useT();
  const accessToken = useAuthStore((s) => s.accessToken);
  const search = useSearchParams();

  // ADR-0011: tab state.
  //   'import'   = Excel/CSV preview + commit (B1a apply-rules polling).
  //   'structure'= the department/position/employee tree (formerly /admin/employees).
  //   'rules'    = B2: edit «course bindings» per position/department.
  // Default from query string so deep-links land on the right tab
  // (used by /admin page quick-link and the legacy /admin/employees
  // redirect).
  type Tab = 'import' | 'structure' | 'rules' | 'company';
  const queryTab = search?.get('tab');
  // Студенту вкладки «Импорт», «Структура», «Правила» не нужны — он
  // потребитель контента, ничего не настраивает (см. ADR-0012).
  // Страница /admin/staff — это admin/methodologist surface. Если
  // зашёл студент — показываем понятное «нет доступа».
  const userRole = useAuthStore((s) => s.user?.role ?? '');
  const isStaffOwnersRole = ['methodologist', 'teacher', 'admin', 'org_admin', 'superadmin'].includes(userRole);
  const allowedTabs: Tab[] = ['import', 'structure']; // 'rules' добавим если isStaffOwnersRole
  if (isStaffOwnersRole) allowedTabs.push('rules');
  if (isStaffOwnersRole) allowedTabs.push('company');
  const initialTab: Tab =
    (queryTab === 'structure' || queryTab === 'rules' || queryTab === 'company') && allowedTabs.includes(queryTab)
      ? (queryTab as Tab)
      : 'import';
  const [tab, setTab] = useState<Tab>(initialTab);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);
  // B2c: после /commit получаем task_id от apply-rules. Запускаем
  // polling через <ApplyRulesProgress/> и держим banner видимым до
  // терминального state.
  const [applyTaskId, setApplyTaskId] = useState<string | null>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    setPreview(null);
  };

  const handlePreview = async () => {
    if (!selectedFile) return;
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const res = await api.post('/v1/admin/staff/import/preview', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setPreview(res.data);
      const s = res.data.summary;
      const invalid = res.data.invalid_rows?.length || 0;
      toast.success(
        `Готово: ${s.create} новых · ${s.update} обновлений · ${s.skip} без изменений${invalid > 0 ? ` · ${invalid} ошибок` : ''}`
      );
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Ошибка чтения файла';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!selectedFile) return;
    if (!preview) return;
    if (preview.invalid_rows && preview.invalid_rows.length > 0) {
      toast.error(`В файле ${preview.invalid_rows.length} строк с ошибками. Исправьте и попробуйте снова.`);
      return;
    }
    if (preview.summary.create === 0 && preview.summary.update === 0) {
      toast.error('Нет строк для применения');
      return;
    }

    if (!confirm(
      `Будет применено:\n` +
      `  • Создано сотрудников: ${preview.summary.create}\n` +
      `  • Обновлено: ${preview.summary.update}\n` +
      `  • Пропущено: ${preview.summary.skip}\n` +
      `  • Создано должностей: ${preview.summary.new_positions}\n` +
      `Продолжить?`
    )) {
      return;
    }

    setCommitting(true);
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const res = await api.post('/v1/admin/staff/import/commit', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const r = res.data;
      toast.success(
        `Импорт завершён: создано ${r.created}, обновлено ${r.updated}, ` +
        `должностей ${r.positions_created}, пропущено ${r.skipped}`
      );
      // Запускаем polling apply-rules ТОЛЬКО если бэк вернул
      // task_id (т.е. были затронутые сотрудники И воркер
      // доступен). Если affected_user_count === 0 — banner не
      // нужен.
      const tid: string | null = r.apply_rules_task_id ?? null;
      setApplyTaskId(tid);
      setSelectedFile(null);
      setPreview(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Ошибка применения';
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setCommitting(false);
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setPreview(null);
    setApplyTaskId(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">📋 Штатное расписание</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Импорт сотрудников из Excel/CSV и просмотр оргструктуры.
        </p>
      </div>

      {!isStaffOwnersRole ? (
        // Student hit /admin/staff (maybe via stale link). Очищаем
        // объяснение, не показываем UI. ADR-0012: студенты не
        // настраивают ничего ни в одном из доменов.
        <Card>
          <CardContent className="p-6 text-center space-y-2">
            <div className="text-4xl">🚫</div>
            <h3 className="text-lg font-bold text-foreground">
              Нет доступа к странице «Штатное расписание»
            </h3>
            <p className="text-sm text-muted-foreground">
              Эта страница для администратора тенанта и методолога.
              Если ты — обучающийся, перейди в «Мои курсы» через меню.
            </p>
          </CardContent>
        </Card>
      ) : (
      <>

      {/* ADR-0011 + ADR-0012: tabs combine import + structure + rules on one page */}
      <div role="tablist" className="flex border-b border-border">
        <button
          role="tab"
          aria-selected={tab === 'import'}
          onClick={() => setTab('import')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'import'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          📥 Импорт
        </button>
        <button
          role="tab"
          aria-selected={tab === 'structure'}
          onClick={() => setTab('structure')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'structure'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          🌳 Структура
        </button>
        <button
          role="tab"
          aria-selected={tab === 'rules'}
          onClick={() => setTab('rules')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'rules'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          📐 Правила
        </button>
        <button
          role="tab"
          aria-selected={tab === 'company'}
          onClick={() => setTab('company')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'company'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          🏢 Курсы компании
        </button>
      </div>

      {tab === 'import' && (
        <div className="space-y-6">

      {/* B2c: apply-rules progress banner — показывается после
         /commit если бэк вернул task_id. Polling внутри компонента. */}
      {applyTaskId && <ApplyRulesProgress taskId={applyTaskId} />}

      {/* Format help */}
      <Card>
        <CardHeader>
          <CardTitle>📄 Формат файла</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-foreground space-y-2">
          <div>Поддерживаются: <strong>.xlsx</strong> (Excel), <strong>.csv</strong> (UTF-8 или Windows-1251).</div>
          <div>
            <strong>Обязательные колонки:</strong> табельный_номер (personnel_number), имя (first_name), фамилия (last_name), отдел (department), должность (position).
          </div>
          <div>
            <strong>Опционально:</strong> email, телефон (phone), дата_приема (hire_date).
          </div>
          <div className="text-muted-foreground text-xs">
            Первая строка — заголовки. Можно на русском или английском. Регистр не важен.
          </div>
        </CardContent>
      </Card>

      {/* Upload + preview */}
      <Card>
        <CardHeader>
          <CardTitle>1️⃣ Загрузить файл</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.csv"
            onChange={handleFileSelect}
            className="block w-full text-sm text-foreground file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20"
          />
          {selectedFile && (
            <div className="flex items-center gap-2 text-sm text-foreground">
              <span>📎 {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} КБ)</span>
            </div>
          )}
          <div className="flex gap-2">
            <Button onClick={handlePreview} disabled={!selectedFile || loading} variant="outline">
              {loading ? 'Читаю...' : 'Предпросмотр'}
            </Button>
            <Button onClick={handleReset} disabled={!selectedFile} variant="outline">
              Сбросить
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Preview results */}
      {preview && (
        <>
          {preview.missing_required_columns && preview.missing_required_columns.length > 0 && (
            <Card>
              <CardContent className="pt-6 text-center space-y-2">
                <div className="text-4xl">❌</div>
                <h3 className="text-lg font-bold text-destructive">Файл не подходит</h3>
                <p className="text-sm text-foreground">
                  Отсутствуют обязательные колонки:{' '}
                  <strong className="text-destructive">
                    {preview.missing_required_columns.join(', ')}
                  </strong>
                </p>
                <p className="text-xs text-muted-foreground">
                  Переименуйте заголовки в файле и попробуйте снова.
                </p>
              </CardContent>
            </Card>
          )}

          {(!preview.missing_required_columns || preview.missing_required_columns.length === 0) && (
            <>
              {/* Summary */}
              <Card>
                <CardHeader>
                  <CardTitle>2️⃣ Предпросмотр изменений</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                    <div className="rounded-lg bg-success/10 p-3 text-center">
                      <div className="text-2xl font-bold text-success">{preview.summary.create}</div>
                      <div className="text-xs text-success">Создать</div>
                    </div>
                    <div className="rounded-lg bg-warning/10 p-3 text-center">
                      <div className="text-2xl font-bold text-warning">{preview.summary.update}</div>
                      <div className="text-xs text-warning">Обновить</div>
                    </div>
                    <div className="rounded-lg bg-muted p-3 text-center">
                      <div className="text-2xl font-bold text-foreground">{preview.summary.skip}</div>
                      <div className="text-xs text-foreground">Без изменений</div>
                    </div>
                    <div className="rounded-lg bg-destructive/10 p-3 text-center">
                      <div className="text-2xl font-bold text-destructive">{preview.summary.new_positions}</div>
                      <div className="text-xs text-destructive">Новых должностей</div>
                    </div>
                  </div>

                  {preview.summary.invalid_rows && preview.summary.invalid_rows > 0 && (
                    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive mb-4">
                      ⚠️ В файле <strong>{preview.summary.invalid_rows}</strong> строк с ошибками — исправьте
                      и перезагрузите. Commit будет заблокирован.
                    </div>
                  )}

                  {preview.new_positions.length > 0 && (
                    <details className="mb-4 text-sm">
                      <summary className="cursor-pointer text-foreground font-medium">
                        Новые должности ({preview.new_positions.length})
                      </summary>
                      <ul className="mt-2 space-y-1 pl-4">
                        {preview.new_positions.map((p, i) => (
                          <li key={i} className="text-foreground text-xs">+ {p}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </CardContent>
              </Card>

              {/* Preview table */}
              {preview.items.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>3️⃣ Строки ({preview.items.length})</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="max-h-96 overflow-y-auto">
                      <Table>
                        <thead className="sticky top-0 bg-muted">
                          <tr>
                            <th className="text-left p-2">Действие</th>
                            <th className="text-left p-2">Таб. №</th>
                            <th className="text-left p-2">ФИО</th>
                            <th className="text-left p-2">Отдел / Должность</th>
                            <th className="text-left p-2">Email</th>
                            <th className="text-left p-2">Заметки</th>
                          </tr>
                        </thead>
                        <tbody>
                          {preview.items.map((item) => (
                            <tr key={item.row_number} className="border-t">
                              <td className="p-2">
                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${ACTION_COLORS[item.action]}`}>
                                  {ACTION_LABELS[item.action]}
                                </span>
                              </td>
                              <td className="p-2 font-mono text-xs">{item.personnel_number}</td>
                              <td className="p-2 text-sm">
                                {item.last_name} {item.first_name}
                              </td>
                              <td className="p-2 text-xs">
                                {item.department}
                                <br />
                <span className="text-muted-foreground">{item.position}</span>
                              </td>
                              <td className="p-2 text-xs text-muted-foreground">
                                {item.email || <span className="text-muted-foreground">—</span>}
                              </td>
                              <td className="p-2 text-[11px] text-muted-foreground">
                                {item.notes.length > 0 ? item.notes.join(' · ') : <span className="text-muted-foreground">—</span>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Invalid rows */}
              {preview.invalid_rows && preview.invalid_rows.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>
                      ⚠️ Ошибки в файле ({preview.invalid_rows.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="max-h-64 overflow-y-auto">
                      <Table>
                        <thead className="sticky top-0 bg-muted">
                          <tr>
                            <th className="text-left p-2">Строка</th>
                            <th className="text-left p-2">Ошибки</th>
                            <th className="text-left p-2">Содержимое</th>
                          </tr>
                        </thead>
                        <tbody>
                          {preview.invalid_rows.map((inv, i) => (
                            <tr key={i} className="border-t">
                              <td className="p-2 text-xs">{inv.row_number}</td>
                              <td className="p-2 text-xs text-destructive">
                                {inv.errors.join(', ')}
                              </td>
                              <td className="p-2 text-xs font-mono text-muted-foreground">
                                {JSON.stringify(inv.raw)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Commit */}
              <div className="flex justify-end gap-2">
                <Button onClick={handleReset} variant="outline">
                  Отменить
                </Button>
                <Button
                  onClick={handleCommit}
                  disabled={
                    committing ||
                    loading ||
                    (preview.invalid_rows && preview.invalid_rows.length > 0) ||
                    (preview.summary.create === 0 && preview.summary.update === 0)
                  }
                >
                  {committing
                    ? 'Применяю...'
                    : `✅ Применить (${preview.summary.create} + ${preview.summary.update})`}
                </Button>
              </div>
            </>
          )}
        </>
      )}
        </div>
      )}

      {tab === 'structure' && <StructureTab />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'company' && <CompanyCoursesTab />}
      </>

      )}
    </div>
  );
}


// ── Structure tab ────────────────────────────────────────────────────

interface StructureEmployee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
  assigned_courses: number;
  completed_courses: number;
  ready_percent: number;
}

interface StructurePosition {
  id: string;
  name: string;
  department: string;
  department_slug: string | null;
  employee_count: number;
  ready_percent: number;
  employees: StructureEmployee[];
}

interface StructureDepartment {
  id: string | null;
  name: string;
  slug: string;
  position_count: number;
  employee_count: number;
  ready_percent: number;
  positions: StructurePosition[];
}

interface StructureResponse {
  departments: StructureDepartment[];
  summary: {
    total_employees: number;
    total_departments: number;
    total_positions: number;
    overall_ready_percent: number;
    total_assigned_courses: number;
    total_completed_courses: number;
  };
}

function StructureTab() {
  const [data, setData] = useState<StructureResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedDepts, setExpandedDepts] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // ADR-0011: new canonical endpoint is /admin/staff/structure. The
        // legacy /admin/staff/tree still works but returns the old shape.
        const res = await api.get('/v1/admin/staff/structure');
        if (!cancelled) setData(res.data);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const toggleDept = (slug: string) => {
    setExpandedDepts((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  if (loading) {
    return <div className="p-6 text-muted-foreground">Загружаю структуру...</div>;
  }
  if (!data || data.departments.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <p>Нет ни одного сотрудника.</p>
        <p className="text-sm mt-2">Используйте вкладку «Импорт» чтобы загрузить штатку из Excel/CSV.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg bg-primary/10 p-3 text-center">
          <div className="text-2xl font-bold text-primary">{data.summary.total_employees}</div>
          <div className="text-xs text-primary">Сотрудников</div>
        </div>
        <div className="rounded-lg bg-accent/10 p-3 text-center">
          <div className="text-2xl font-bold text-accent">{data.summary.total_departments}</div>
          <div className="text-xs text-accent">Отделов</div>
        </div>
        <div className="rounded-lg bg-muted p-3 text-center">
          <div className="text-2xl font-bold text-foreground">{data.summary.total_positions}</div>
          <div className="text-xs text-foreground">Должностей</div>
        </div>
        <div className="rounded-lg bg-success/10 p-3 text-center">
          <div className="text-2xl font-bold text-success">{data.summary.overall_ready_percent}%</div>
          <div className="text-xs text-success">Готово</div>
        </div>
      </div>

      {/* Department tree */}
      <Card>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {data.departments.map((dept) => {
              const isOpen = expandedDepts.has(dept.slug);
              return (
                <li key={dept.slug}>
                  <button
                    type="button"
                    onClick={() => toggleDept(dept.slug)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center gap-3 px-4 py-3 hover:bg-muted/40 transition-colors text-left"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-bold text-primary">
                      🏢
                    </span>
                    <span className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-foreground">{dept.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {dept.position_count} должностей · {dept.employee_count} сотрудников
                      </div>
                    </span>
                    <span className="text-xs font-medium text-muted-foreground">{dept.ready_percent}%</span>
                  </button>
                  {isOpen && (
                    <ul className="bg-muted/30 divide-y divide-border">
                      {dept.positions.length === 0 && (
                        <li className="px-4 py-3 pl-14 text-xs text-muted-foreground italic">
                          Нет должностей
                        </li>
                      )}
                      {dept.positions.map((pos) => (
                        <li key={pos.id} className="px-4 py-3 pl-14">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-foreground">{pos.name}</div>
                              <div className="text-xs text-muted-foreground mt-0.5">
                                {pos.employee_count} сотрудников · {pos.ready_percent}% готово
                              </div>
                              {pos.employees.length > 0 && (
                                <ul className="mt-2 space-y-1">
                                  {pos.employees.map((emp) => (
                                    <li key={emp.id} className="text-xs flex items-center gap-2">
                                      <span className={emp.is_active ? 'text-foreground' : 'text-muted-foreground line-through'}>
                                        {emp.full_name}
                                        {emp.personnel_number && (
                                          <span className="text-muted-foreground ml-1">
                                            ({emp.personnel_number})
                                          </span>
                                        )}
                                      </span>
                                      <span className="ml-auto text-muted-foreground">
                                        {emp.completed_courses}/{emp.assigned_courses} курсов
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
