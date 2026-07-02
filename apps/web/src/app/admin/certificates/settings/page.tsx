'use client';

import { useEffect, useState } from 'react';
import { Award, Eye, Save } from 'lucide-react';

import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

interface CertificateSettings {
  organization_name: string;
  signer_name: string;
  signer_title: string;
  validity_months: number | null;
  footer_note: string;
  verification_base_url: string;
  show_verification_url: boolean;
}

const defaults: CertificateSettings = {
  organization_name: 'Kamilya LMS',
  signer_name: '',
  signer_title: '',
  validity_months: null,
  footer_note: '',
  verification_base_url: 'https://app.kml.kz/certificates',
  show_verification_url: true,
};

export default function CertificateSettingsPage() {
  const [settings, setSettings] = useState<CertificateSettings>(defaults);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await api.get('/v1/certificates/settings');
        if (!cancelled) setSettings({ ...defaults, ...res.data });
      } catch (err: any) {
        toast.error('Не удалось загрузить настройки сертификатов', {
          description: err?.response?.data?.detail || err?.message,
        });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const update = <K extends keyof CertificateSettings>(key: K, value: CertificateSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...settings,
        validity_months: settings.validity_months && settings.validity_months > 0
          ? settings.validity_months
          : null,
      };
      const res = await api.put('/v1/certificates/settings', payload);
      setSettings({ ...defaults, ...res.data });
      toast.success('Настройки сертификатов сохранены');
    } catch (err: any) {
      toast.error('Не удалось сохранить настройки', {
        description: err?.response?.data?.detail || err?.message,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Шаблон сертификата</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Эти настройки применяются к новым сертификатам и к PDF, которые будут пересозданы при скачивании.
          </p>
        </div>
        <Button onClick={save} disabled={saving || loading} className="gap-2">
          <Save className="h-4 w-4" aria-hidden="true" />
          {saving ? 'Сохранение...' : 'Сохранить'}
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Данные на сертификате</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                Загрузка...
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="certificate-organization" className="mb-1 block text-sm font-medium">
                    Организация
                  </label>
                  <Input
                    id="certificate-organization"
                    value={settings.organization_name}
                    onChange={(event) => update('organization_name', event.target.value)}
                    placeholder="ТОО Kamilya Foods"
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="certificate-signer-name" className="mb-1 block text-sm font-medium">
                      Подписант
                    </label>
                    <Input
                      id="certificate-signer-name"
                      value={settings.signer_name}
                      onChange={(event) => update('signer_name', event.target.value)}
                      placeholder="Аскар Амирханов"
                    />
                  </div>
                  <div>
                    <label htmlFor="certificate-signer-title" className="mb-1 block text-sm font-medium">
                      Должность подписанта
                    </label>
                    <Input
                      id="certificate-signer-title"
                      value={settings.signer_title}
                      onChange={(event) => update('signer_title', event.target.value)}
                      placeholder="HR директор"
                    />
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="certificate-validity" className="mb-1 block text-sm font-medium">
                      Срок действия, месяцев
                    </label>
                    <Input
                      id="certificate-validity"
                      type="number"
                      min={0}
                      max={120}
                      value={settings.validity_months ?? ''}
                      onChange={(event) => update(
                        'validity_months',
                        event.target.value ? Number(event.target.value) : null,
                      )}
                      placeholder="Без срока"
                    />
                  </div>
                  <div>
                    <label htmlFor="certificate-verify-url" className="mb-1 block text-sm font-medium">
                      URL проверки
                    </label>
                    <Input
                      id="certificate-verify-url"
                      value={settings.verification_base_url}
                      onChange={(event) => update('verification_base_url', event.target.value)}
                      placeholder="https://app.kml.kz/certificates"
                    />
                  </div>
                </div>

                <label className="flex items-center gap-2 rounded-xl border border-border p-3 text-sm">
                  <input
                    type="checkbox"
                    checked={settings.show_verification_url}
                    onChange={(event) => update('show_verification_url', event.target.checked)}
                    className="h-4 w-4 rounded border-border text-primary focus:ring-primary"
                  />
                  Показывать ссылку проверки на PDF
                </label>

                <div>
                  <label htmlFor="certificate-footer-note" className="mb-1 block text-sm font-medium">
                    Примечание внизу сертификата
                  </label>
                  <textarea
                    id="certificate-footer-note"
                    value={settings.footer_note}
                    onChange={(event) => update('footer_note', event.target.value)}
                    rows={3}
                    className="w-full rounded-xl border border-border bg-card px-3 py-2.5 text-sm outline-none transition-colors focus:border-primary"
                    placeholder="Например: сертификат подтверждает прохождение внутреннего обучения компании."
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Eye className="h-5 w-5 text-primary" aria-hidden="true" />
              Предпросмотр
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-2xl border border-border bg-gradient-to-br from-white to-muted p-5 text-center shadow-sm">
              <Award className="mx-auto h-10 w-10 text-primary" aria-hidden="true" />
              <div className="mt-4 text-xl font-bold text-primary">CERTIFICATE</div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">OF COMPLETION</div>
              <div className="mt-6 text-xs text-muted-foreground">This is to certify that</div>
              <div className="mt-2 text-lg font-semibold">Имя сотрудника</div>
              <div className="mt-4 text-xs text-muted-foreground">has successfully completed the course</div>
              <div className="mt-2 text-sm font-semibold text-primary">Название курса</div>
              <div className="mt-6 text-xs text-muted-foreground">
                Issued by {settings.organization_name || 'Kamilya LMS'}
              </div>
              {(settings.signer_name || settings.signer_title) && (
                <div className="mt-4 border-t border-border pt-3 text-xs">
                  <div className="font-medium">{settings.signer_name}</div>
                  <div className="text-muted-foreground">{settings.signer_title}</div>
                </div>
              )}
              {settings.footer_note && (
                <div className="mt-3 text-[11px] text-muted-foreground">{settings.footer_note}</div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
