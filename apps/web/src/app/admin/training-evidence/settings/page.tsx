'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Loader2, Save } from 'lucide-react';

import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { isPdfPreview } from '@/lib/pdfPreview';
import PdfPreview from '@/components/PdfPreview';

interface FormSettings {
  template_version: number;
  organization_name: string;
  title: string;
  intro_text: string;
  confirmation_text: string;
  quiz_title: string;
  quiz_intro_text: string;
  quiz_confirmation_text: string;
  employee_signature_label: string;
  employee_date_label: string;
  representative_signature_label: string;
  representative_date_label: string;
  representative_name: string;
  representative_title: string;
  footer_note: string;
  selected_fields: string[] | null;
}

interface FormField {
  id: string;
  label: string;
  group: string;
  required: boolean;
}

interface FormFieldCatalog {
  fields: FormField[];
  default_selected_fields: string[];
}

const defaults: FormSettings = {
  template_version: 1,
  organization_name: 'Kamilya LMS',
  title: 'Подтверждение прохождения курса',
  intro_text: 'Документ подтверждает завершение сотрудником опубликованной версии курса.',
  confirmation_text: 'Я подтверждаю, что завершил(а) указанный курс, ознакомился(лась) с его материалами и самостоятельно прошел(ла) обязательное тестирование.',
  quiz_title: 'Результат отдельного теста',
  quiz_intro_text: 'Документ фиксирует результат отдельного теста и не подтверждает завершение курса.',
  quiz_confirmation_text: 'Подтверждаю самостоятельное выполнение указанного теста. Результат приведён в документе.',
  employee_signature_label: 'Подпись сотрудника',
  employee_date_label: 'Дата',
  representative_signature_label: 'Подпись представителя работодателя',
  representative_date_label: 'Дата проверки',
  representative_name: '',
  representative_title: '',
  footer_note: '',
  selected_fields: null,
};

export default function TrainingEvidenceFormSettingsPage() {
  const [settings, setSettings] = useState<FormSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [previewActivity, setPreviewActivity] = useState<'course' | 'quiz'>('course');
  const [catalog, setCatalog] = useState<FormFieldCatalog | null>(null);
  const [settingsError, setSettingsError] = useState(false);
  const [catalogError, setCatalogError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [previewFingerprint, setPreviewFingerprint] = useState<string | null>(null);
  const previewGenerationRef = useRef(0);
  const previewUrlRef = useRef<string | null>(null);
  const draftFingerprintRef = useRef('');

  const replacePreview = useCallback((url: string | null, blob: Blob | null = null) => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = url;
    setPreviewUrl(url);
    setPreviewBlob(blob);
  }, []);

  const draftFingerprint = JSON.stringify({ settings, previewActivity });
  draftFingerprintRef.current = draftFingerprint;
  const dataReady = !loading && !settingsError && !catalogError && catalog !== null;
  const editingDisabled = loading || saving || settingsError || catalogError || !catalog;

  const renderPreview = useCallback(async (value: FormSettings, fingerprint: string, signal?: AbortSignal) => {
    const generation = ++previewGenerationRef.current;
    setPreviewLoading(true);
    setPreviewFingerprint(null);
    try {
      const previewUrl = previewActivity === 'quiz'
        ? '/v1/training-evidence/form-settings/preview?activity=quiz'
        : '/v1/training-evidence/form-settings/preview';
      const response = await api.post<Blob>(previewUrl, value, { responseType: 'blob', signal });
      if (!await isPdfPreview(response.data)) throw new Error('Invalid PDF preview');
      if (signal?.aborted || generation !== previewGenerationRef.current) return null;
      const url = URL.createObjectURL(response.data);
      replacePreview(url, response.data);
      setPreviewFingerprint(fingerprint);
      return url;
    } catch {
      if (signal?.aborted || generation !== previewGenerationRef.current) return null;
      replacePreview(null);
      setPreviewFingerprint(null);
      toast.error('Не удалось сформировать предпросмотр бланка.');
      return null;
    } finally {
      if (!signal?.aborted && generation === previewGenerationRef.current) setPreviewLoading(false);
    }
  }, [previewActivity, replacePreview]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSettingsError(false);
    setCatalogError(false);
    Promise.all([
      api.get<FormSettings>('/v1/training-evidence/form-settings'),
      api.get<FormFieldCatalog>('/v1/training-evidence/form-fields'),
    ])
      .then(([settingsResponse, catalogResponse]) => {
        if (cancelled) return;
        setSettings({ ...defaults, ...settingsResponse.data });
        setCatalog(catalogResponse.data);
      })
      .catch((error: { config?: { url?: string } }) => {
        if (cancelled) return;
        const endpoint = error?.config?.url ?? '';
        if (endpoint.includes('/form-fields')) setCatalogError(true);
        else setSettingsError(true);
        toast.error('Не удалось загрузить настройки или список полей бланка.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [loadAttempt]);

  useEffect(() => {
    if (!dataReady) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => { void renderPreview(settings, draftFingerprint, controller.signal); }, 500);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
      previewGenerationRef.current += 1;
      setPreviewLoading(false);
    };
  }, [dataReady, draftFingerprint, renderPreview, settings]);

  useEffect(() => () => {
    previewGenerationRef.current += 1;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const update = <K extends keyof FormSettings>(key: K, value: FormSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const configureFields = () => {
    if (!catalog || editingDisabled) return;
    update('selected_fields', [...catalog.default_selected_fields]);
  };

  const toggleField = (field: FormField, checked: boolean) => {
    if (editingDisabled || field.required) return;
    const selected = settings.selected_fields ?? [];
    update('selected_fields', checked ? [...selected, field.id] : selected.filter((id) => id !== field.id));
  };

  const save = async () => {
    setSaving(true);
    const requestFingerprint = draftFingerprint;
    try {
      const response = await api.put<FormSettings>('/v1/training-evidence/form-settings', settings);
      if (draftFingerprintRef.current === requestFingerprint) {
        setSettings({ ...defaults, ...response.data });
      }
      toast.success('Шаблон сохранён. Он применяется к новым завершениям курса и новым попыткам тестов с включённым выбором полей.');
    } catch {
      toast.error('Не удалось сохранить бланк подтверждения.');
    } finally {
      setSaving(false);
    }
  };

  const downloadPreview = async () => {
    if (previewLoading || previewFingerprint !== draftFingerprint) return;
    const url = previewUrl;
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
            Настройте печатные формы завершения курса и отдельного теста. Выбранные поля и тексты сохраняются вместе с новым результатом и не меняются задним числом при настройке шаблона.
          </p>
        </div>
        <Button onClick={() => void save()} disabled={!dataReady || saving}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Сохранить
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader><CardTitle>Содержание бланка</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            {loading ? <div className="py-16 text-center text-muted-foreground">Загрузка…</div> : settingsError || catalogError ? <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm" role="alert">
              <p>Не удалось загрузить настройки бланка или доступные поля. Редактирование и сохранение отключены, чтобы не перезаписать текущую конфигурацию.</p>
              <Button type="button" variant="outline" onClick={() => setLoadAttempt((value) => value + 1)}>Повторить загрузку</Button>
            </div> : <fieldset disabled={editingDisabled} className="space-y-5">
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
              <div className="space-y-4 rounded-md border border-primary/30 bg-primary/5 p-4">
                <div>
                  <h3 className="text-sm font-semibold">Отдельный тест</h3>
                  <p className="mt-1 text-xs text-muted-foreground">Эти тексты используются только в результате отдельной попытки теста. Выбор полей ниже применяется и к такому результату.</p>
                </div>
                {textField('quiz_title', 'Заголовок результата теста', 160)}
                <div>
                  <label htmlFor="evidence-form-quiz-intro" className="mb-2 block text-sm font-medium">Вводный текст результата теста</label>
                  <textarea id="evidence-form-quiz-intro" className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" maxLength={1000} value={settings.quiz_intro_text} onChange={(event) => update('quiz_intro_text', event.target.value)} />
                </div>
                <div>
                  <label htmlFor="evidence-form-quiz-confirmation" className="mb-2 block text-sm font-medium">Текст подтверждения результата теста</label>
                  <textarea id="evidence-form-quiz-confirmation" className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" maxLength={1500} value={settings.quiz_confirmation_text} onChange={(event) => update('quiz_confirmation_text', event.target.value)} />
                </div>
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
              <fieldset className="space-y-3 rounded-md border p-4">
                <legend className="px-1 text-sm font-semibold">Поля печатной формы</legend>
                <p className="text-xs text-muted-foreground">Выбор полей меняет только печатный бланк. Полный акт доказательств обучения по-прежнему сохраняет все факты. Номер сотрудника, подразделение и должность берутся из текущего профиля на момент экспорта и не являются историческими данными.</p>
                {settings.selected_fields === null ? <div className="space-y-3 text-sm">
                  <p>Сейчас используется исторический формат бланка без явного выбора полей.</p>
                  <Button type="button" variant="outline" onClick={configureFields} disabled={editingDisabled}>Настроить поля</Button>
                </div> : <div className="space-y-4">
                  {Array.from(new Set(catalog?.fields.map((field) => field.group) ?? [])).map((group) => {
                    const fields = catalog?.fields.filter((field) => field.group === group) ?? [];
                    if (!fields.length) return null;
                    return <div key={group}>
                      <h3 className="mb-2 text-sm font-medium">{group}</h3>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {fields.map((field) => <label key={field.id} className="flex min-h-10 items-center gap-3 rounded border px-3 text-sm">
                          <input type="checkbox" className="h-4 w-4" checked={field.required || (settings.selected_fields?.includes(field.id) ?? false)} disabled={editingDisabled || field.required} onChange={(event) => toggleField(field, event.target.checked)} aria-label={field.label} />
                          <span>{field.label}{field.required ? <span className="ml-1 text-xs text-muted-foreground">(обязательно)</span> : null}</span>
                        </label>)}
                      </div>
                    </div>;
                  })}
                </div>}
              </fieldset>
            </fieldset>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-4">
            <div><CardTitle>Предпросмотр PDF</CardTitle><p className="mt-1 text-sm text-muted-foreground">Данные сотрудника и курса здесь демонстрационные.</p></div>
            <Button variant="outline" onClick={() => void downloadPreview()} disabled={previewLoading || previewFingerprint !== draftFingerprint || !previewUrl}>
              <Download className="mr-2 h-4 w-4" /> Скачать
            </Button>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Тип предпросмотра">
              <Button type="button" variant={previewActivity === 'course' ? 'default' : 'outline'} onClick={() => setPreviewActivity('course')} disabled={editingDisabled}>Завершение курса</Button>
              <Button type="button" variant={previewActivity === 'quiz' ? 'default' : 'outline'} onClick={() => setPreviewActivity('quiz')} disabled={editingDisabled}>Отдельный тест</Button>
            </div>
            {previewActivity === 'quiz' && <p className="mb-3 text-sm text-muted-foreground">Предпросмотр использует тексты отдельного теста. Выбранные поля применятся к новым результатам тестов. Название теста и ID попытки отображаются всегда, чтобы однозначно определить результат. Для включения нового бланка нажмите «Настроить поля» и сохраните шаблон; старые попытки не переоформляются.</p>}
            {dataReady && previewFingerprint !== draftFingerprint && <p role="status" className="mb-3 text-sm text-muted-foreground">Образец обновляется. Скачивание станет доступно после обновления.</p>}
            {previewLoading && !previewBlob ? <div className="flex min-h-[620px] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin" /></div> : previewBlob ? (
              <PdfPreview blob={previewBlob} title="Предпросмотр бланка подтверждения"
                loadingLabel="Загрузка предпросмотра…" errorLabel="Не удалось показать PDF. Попробуйте скачать образец." />
            ) : <div className="flex min-h-[620px] items-center justify-center text-sm text-muted-foreground">Предпросмотр недоступен</div>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
