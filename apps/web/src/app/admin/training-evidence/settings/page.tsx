'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Loader2, Save } from 'lucide-react';

import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface FormSettings {
  template_version: number;
  organization_name: string;
  title: string;
  intro_text: string;
  confirmation_text: string;
  employee_signature_label: string;
  employee_date_label: string;
  representative_signature_label: string;
  representative_date_label: string;
  representative_name: string;
  representative_title: string;
  footer_note: string;
}

const defaults: FormSettings = {
  template_version: 1,
  organization_name: 'Kamilya LMS',
  title: 'Подтверждение прохождения курса',
  intro_text: 'Документ подтверждает завершение сотрудником опубликованной версии курса.',
  confirmation_text: 'Я подтверждаю, что завершил(а) указанный курс, ознакомился(лась) с его материалами и самостоятельно прошел(ла) обязательное тестирование.',
  employee_signature_label: 'Подпись сотрудника',
  employee_date_label: 'Дата',
  representative_signature_label: 'Подпись представителя работодателя',
  representative_date_label: 'Дата проверки',
  representative_name: '',
  representative_title: '',
  footer_note: '',
};

export default function TrainingEvidenceFormSettingsPage() {
  const [settings, setSettings] = useState<FormSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const replacePreview = useCallback((url: string | null) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = url;
    setPreviewUrl(url);
  }, []);

  const renderPreview = useCallback(async (value: FormSettings) => {
    setPreviewLoading(true);
    try {
      const response = await api.post<Blob>('/v1/training-evidence/form-settings/preview', value, { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      replacePreview(url);
      return url;
    } catch {
      toast.error('Не удалось сформировать предпросмотр бланка.');
      return null;
    } finally {
      setPreviewLoading(false);
    }
  }, [replacePreview]);

  useEffect(() => {
    let cancelled = false;
    void api.get<FormSettings>('/v1/training-evidence/form-settings')
      .then((response) => {
        if (!cancelled) setSettings({ ...defaults, ...response.data });
      })
      .catch(() => toast.error('Не удалось загрузить настройки бланка.'))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (loading) return;
    const timeout = window.setTimeout(() => { void renderPreview(settings); }, 500);
    return () => window.clearTimeout(timeout);
  }, [loading, renderPreview, settings]);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const update = <K extends keyof FormSettings>(key: K, value: FormSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const response = await api.put<FormSettings>('/v1/training-evidence/form-settings', settings);
      setSettings(response.data);
      toast.success('Бланк подтверждения сохранён. Новые завершения курса получат эту версию.');
    } catch {
      toast.error('Не удалось сохранить бланк подтверждения.');
    } finally {
      setSaving(false);
    }
  };

  const downloadPreview = async () => {
    const url = previewUrl || await renderPreview(settings);
    if (!url) return;
    const link = document.createElement('a');
    link.href = url;
    link.download = 'training-completion-form-preview.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const textField = (key: keyof FormSettings, label: string, maxLength: number) => (
    <div>
      <label htmlFor={`evidence-form-${key}`} className="mb-2 block text-sm font-medium">{label}</label>
      <Input
        id={`evidence-form-${key}`}
        value={String(settings[key] ?? '')}
        maxLength={maxLength}
        onChange={(event) => update(key, event.target.value as never)}
      />
    </div>
  );

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Бланк подтверждения прохождения</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Настройте печатную форму для новых завершений курса. Версия бланка фиксируется вместе с событием завершения и не меняется задним числом.
          </p>
        </div>
        <Button onClick={() => void save()} disabled={loading || saving}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Сохранить
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader><CardTitle>Содержание бланка</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            {loading ? <div className="py-16 text-center text-muted-foreground">Загрузка…</div> : <>
              {textField('organization_name', 'Название организации', 160)}
              {textField('title', 'Заголовок документа', 160)}
              <div>
                <label htmlFor="evidence-form-intro" className="mb-2 block text-sm font-medium">Вводный текст</label>
                <textarea id="evidence-form-intro" className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" maxLength={1000} value={settings.intro_text} onChange={(event) => update('intro_text', event.target.value)} />
              </div>
              <div>
                <label htmlFor="evidence-form-confirmation" className="mb-2 block text-sm font-medium">Текст подтверждения сотрудника</label>
                <textarea id="evidence-form-confirmation" className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" maxLength={1500} value={settings.confirmation_text} onChange={(event) => update('confirmation_text', event.target.value)} />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {textField('employee_signature_label', 'Подпись сотрудника', 120)}
                {textField('employee_date_label', 'Дата сотрудника', 120)}
                {textField('representative_signature_label', 'Подпись представителя', 120)}
                {textField('representative_date_label', 'Дата проверки', 120)}
                {textField('representative_name', 'ФИО представителя', 160)}
                {textField('representative_title', 'Должность представителя', 160)}
              </div>
              <div>
                <label htmlFor="evidence-form-footer" className="mb-2 block text-sm font-medium">Примечание внизу</label>
                <textarea id="evidence-form-footer" className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" maxLength={500} value={settings.footer_note} onChange={(event) => update('footer_note', event.target.value)} />
              </div>
            </>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>Предпросмотр PDF</CardTitle><p className="mt-1 text-sm text-muted-foreground">Данные сотрудника и курса здесь демонстрационные.</p></div>
            <Button variant="outline" onClick={() => void downloadPreview()} disabled={previewLoading}>
              <Download className="mr-2 h-4 w-4" /> Скачать
            </Button>
          </CardHeader>
          <CardContent>
            {previewLoading && !previewUrl ? <div className="flex min-h-[620px] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin" /></div> : previewUrl ? (
              <iframe title="Предпросмотр бланка подтверждения" src={previewUrl} className="h-[720px] w-full rounded-md border" />
            ) : <div className="flex min-h-[620px] items-center justify-center text-sm text-muted-foreground">Предпросмотр недоступен</div>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
