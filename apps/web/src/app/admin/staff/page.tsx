'use client';

import { useState, useRef } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge, Table } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

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
  create: 'bg-emerald-100 text-emerald-700',
  update: 'bg-amber-100 text-amber-700',
  skip: 'bg-warm-100 text-warm-500',
};

export default function AdminStaffPage() {
  const { t } = useT();
  const accessToken = useAuthStore((s) => s.accessToken);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [committing, setCommitting] = useState(false);

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
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-warm-800">📋 Штатное расписание</h1>
        <p className="text-sm text-warm-500 mt-1">
          Загрузите список сотрудников из Excel/CSV. Система сопоставит табельные номера
          с существующими пользователями, создаст должности (если новые) и обновит данные.
        </p>
      </div>

      {/* Format help */}
      <Card>
        <CardHeader>
          <CardTitle>📄 Формат файла</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-warm-600 space-y-2">
          <div>Поддерживаются: <strong>.xlsx</strong> (Excel), <strong>.csv</strong> (UTF-8 или Windows-1251).</div>
          <div>
            <strong>Обязательные колонки:</strong> табельный_номер (personnel_number), имя (first_name), фамилия (last_name), отдел (department), должность (position).
          </div>
          <div>
            <strong>Опционально:</strong> email, телефон (phone), дата_приема (hire_date).
          </div>
          <div className="text-warm-400 text-xs">
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
            className="block w-full text-sm text-warm-700 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20"
          />
          {selectedFile && (
            <div className="flex items-center gap-2 text-sm text-warm-600">
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
                <h3 className="text-lg font-bold text-red-700">Файл не подходит</h3>
                <p className="text-sm text-warm-600">
                  Отсутствуют обязательные колонки:{' '}
                  <strong className="text-red-700">
                    {preview.missing_required_columns.join(', ')}
                  </strong>
                </p>
                <p className="text-xs text-warm-500">
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
                    <div className="rounded-lg bg-emerald-50 p-3 text-center">
                      <div className="text-2xl font-bold text-emerald-700">{preview.summary.create}</div>
                      <div className="text-xs text-emerald-600">Создать</div>
                    </div>
                    <div className="rounded-lg bg-amber-50 p-3 text-center">
                      <div className="text-2xl font-bold text-amber-700">{preview.summary.update}</div>
                      <div className="text-xs text-amber-600">Обновить</div>
                    </div>
                    <div className="rounded-lg bg-warm-50 p-3 text-center">
                      <div className="text-2xl font-bold text-warm-700">{preview.summary.skip}</div>
                      <div className="text-xs text-warm-600">Без изменений</div>
                    </div>
                    <div className="rounded-lg bg-rose-50 p-3 text-center">
                      <div className="text-2xl font-bold text-rose-700">{preview.summary.new_positions}</div>
                      <div className="text-xs text-rose-600">Новых должностей</div>
                    </div>
                  </div>

                  {preview.summary.invalid_rows && preview.summary.invalid_rows > 0 && (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 mb-4">
                      ⚠️ В файле <strong>{preview.summary.invalid_rows}</strong> строк с ошибками — исправьте
                      и перезагрузите. Commit будет заблокирован.
                    </div>
                  )}

                  {preview.new_positions.length > 0 && (
                    <details className="mb-4 text-sm">
                      <summary className="cursor-pointer text-warm-700 font-medium">
                        Новые должности ({preview.new_positions.length})
                      </summary>
                      <ul className="mt-2 space-y-1 pl-4">
                        {preview.new_positions.map((p, i) => (
                          <li key={i} className="text-warm-600 text-xs">+ {p}</li>
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
                        <thead className="sticky top-0 bg-warm-50">
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
                <span className="text-warm-400">{item.position}</span>
                              </td>
                              <td className="p-2 text-xs text-warm-500">
                                {item.email || <span className="text-warm-300">—</span>}
                              </td>
                              <td className="p-2 text-[11px] text-warm-500">
                                {item.notes.length > 0 ? item.notes.join(' · ') : <span className="text-warm-300">—</span>}
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
                        <thead className="sticky top-0 bg-warm-50">
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
                              <td className="p-2 text-xs text-red-700">
                                {inv.errors.join(', ')}
                              </td>
                              <td className="p-2 text-xs font-mono text-warm-500">
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
  );
}
