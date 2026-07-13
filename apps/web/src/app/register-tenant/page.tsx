'use client';

import { FormEvent, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Building2, CheckCircle2, Mail, MessageCircle, ShieldCheck, Sparkles } from 'lucide-react';

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { Logo } from '@/components/brand/Logo';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';

type TenantIntent = 'try' | 'demo' | 'buy';

const intentOptions: Array<{ value: TenantIntent; label: string; hint: string }> = [
  { value: 'try', label: 'Попробовать', hint: '14 дней и бесплатная генерация' },
  { value: 'demo', label: 'Демо', hint: 'Показать сценарий команде' },
  { value: 'buy', label: 'Купить', hint: 'Передать заявку менеджеру' },
];

const employeeRanges = ['1-10', '11-50', '51-200', '201-1000', '1000+'];

function formatKzPhone(value: string): string {
  const digits = value.replace(/\D/g, '');
  let local = digits;

  if (local.startsWith('8')) {
    local = local.slice(1);
  } else if (local.startsWith('7')) {
    local = local.slice(1);
  }

  local = local.slice(0, 10);
  const parts = [
    local.slice(0, 3),
    local.slice(3, 6),
    local.slice(6, 8),
    local.slice(8, 10),
  ];

  if (!local) return '';
  let formatted = '+7';
  if (parts[0]) formatted += ` (${parts[0]}`;
  if (parts[0]?.length === 3) formatted += ')';
  if (parts[1]) formatted += ` ${parts[1]}`;
  if (parts[2]) formatted += `-${parts[2]}`;
  if (parts[3]) formatted += `-${parts[3]}`;
  return formatted;
}

export default function TenantRegisterPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [companyName, setCompanyName] = useState('');
  const [contactName, setContactName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [phone, setPhone] = useState('');
  const [telegramUsername, setTelegramUsername] = useState('');
  const [employeeCountRange, setEmployeeCountRange] = useState('');
  const [intent, setIntent] = useState<TenantIntent>('try');
  const [billingIdentifier, setBillingIdentifier] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const canSubmit = useMemo(() => {
    return companyName.trim().length >= 2
      && contactName.trim().length >= 2
      && email.trim().length > 3
      && password.length >= 8;
  }, [companyName, contactName, email, password]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');

    if (!canSubmit) {
      setError('Заполните компанию, контактное лицо, email и пароль от 8 символов.');
      return;
    }

    setLoading(true);
    try {
      const { data } = await api.post('/v1/tenants/register', {
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        email: email.trim(),
        password,
        phone: phone.trim() || null,
        telegram_username: telegramUsername.trim() || null,
        employee_count_range: employeeCountRange || null,
        preferred_language: 'ru',
        intent,
        billing_identifier: billingIdentifier.trim() || null,
        message: message.trim() || null,
      });

      login(data.access_token, data.user);
      toast.success('Trial создан', {
        description: `${data.tenant_name}: 1 обычный AI-курс и 1 курс по должностной инструкции доступны бесплатно.`,
      });
      router.push('/dashboard');
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const messageText =
        (typeof detail === 'object' && detail?.message) ||
        (typeof detail === 'string' && detail) ||
        err?.message ||
        'Не удалось создать trial. Попробуйте еще раз.';
      setError(messageText);
      toast.error('Ошибка регистрации', { description: messageText });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main-content" className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl grid-cols-1 gap-8 px-4 py-8 lg:grid-cols-[1fr_420px] lg:items-center lg:px-8">
        <section className="space-y-6">
          <div className="flex items-center gap-3">
            <Logo variant="full" size={44} />
            <Badge variant="outline">Trial 14 дней</Badge>
          </div>

          <div className="max-w-2xl space-y-4">
            <h1 className="text-3xl font-semibold leading-tight text-foreground md:text-4xl">
              Создайте рабочее пространство Kamilya LMS для вашей компании
            </h1>
            <p className="text-base text-muted-foreground">
              Первый пользователь становится администратором тенанта. В trial входит бесплатная генерация
              одного обычного курса и одного курса на основе должностной инструкции.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Card>
              <CardHeader className="p-4 pb-2">
                <Sparkles className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">2 AI-генерации</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                1 обычный курс и 1 курс по должностной инструкции.
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="p-4 pb-2">
                <ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">До 10 обучающихся</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                Достаточно для проверки полного учебного flow.
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="p-4 pb-2">
                <MessageCircle className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">Бот позже</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                Старт без собственного бота, подключение после квалификации.
              </CardContent>
            </Card>
          </div>
        </section>

        <Card className="w-full">
          <CardHeader>
            <div className="flex items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xl">Регистрация тенанта</CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  Доступ откроется сразу после отправки формы.
                </p>
              </div>
              <Building2 className="h-6 w-6 text-primary" aria-hidden="true" />
            </div>
          </CardHeader>
          <CardContent>
            {error && (
              <div className="mb-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive" role="alert">
                {error}
              </div>
            )}

            <form className="space-y-4" onSubmit={handleSubmit}>
              <div>
                <label htmlFor="company_name" className="mb-1 block text-sm font-medium">
                  <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                  Компания
                </label>
                <Input
                  id="company_name"
                  value={companyName}
                  onChange={(event) => setCompanyName(event.target.value)}
                  autoComplete="organization"
                  placeholder="ТОО Kamilya Foods"
                  required
                  aria-required="true"
                />
              </div>

              <div>
                <label htmlFor="contact_name" className="mb-1 block text-sm font-medium">
                  <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                  Контактное лицо
                </label>
                <Input
                  id="contact_name"
                  value={contactName}
                  onChange={(event) => setContactName(event.target.value)}
                  autoComplete="name"
                  placeholder="Камилла Ахметова"
                  required
                  aria-required="true"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="email" className="mb-1 block text-sm font-medium">
                    <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                    Email
                  </label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    autoComplete="email"
                    placeholder="hr@company.kz"
                    required
                    aria-required="true"
                  />
                </div>
                <div>
                  <label htmlFor="password" className="mb-1 block text-sm font-medium">
                    <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                    Пароль
                  </label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    required
                    aria-required="true"
                    aria-describedby="password-hint"
                  />
                  <p id="password-hint" className="mt-1 text-xs text-muted-foreground">
                    Minimum 8 characters
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="phone" className="mb-1 block text-sm font-medium">
                    Телефон
                  </label>
                  <Input
                    id="phone"
                    value={phone}
                    onChange={(event) => setPhone(formatKzPhone(event.target.value))}
                    autoComplete="tel"
                    inputMode="tel"
                    placeholder="+7 (777) 000-00-00"
                  />
                </div>
                <div>
                  <label htmlFor="telegram" className="mb-1 block text-sm font-medium">
                    Telegram
                  </label>
                  <Input
                    id="telegram"
                    value={telegramUsername}
                    onChange={(event) => setTelegramUsername(event.target.value)}
                    placeholder="@username"
                  />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="employees" className="mb-1 block text-sm font-medium">
                    Размер компании
                  </label>
                  <select
                    id="employees"
                    value={employeeCountRange}
                    onChange={(event) => setEmployeeCountRange(event.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    <option value="">Не выбрано</option>
                    {employeeRanges.map((range) => (
                      <option key={range} value={range}>{range}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="billing_identifier" className="mb-1 block text-sm font-medium">
                    БИН/ИИН
                  </label>
                  <Input
                    id="billing_identifier"
                    value={billingIdentifier}
                    onChange={(event) => setBillingIdentifier(event.target.value)}
                    placeholder="Опционально"
                  />
                </div>
              </div>

              <div>
                <span className="mb-2 block text-sm font-medium">Цель</span>
                <div className="grid gap-2 sm:grid-cols-3">
                  {intentOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setIntent(option.value)}
                      className={[
                        'rounded-md border p-3 text-left text-sm transition-colors',
                        intent === option.value
                          ? 'border-primary bg-primary/10 text-foreground'
                          : 'border-input bg-background hover:bg-accent',
                      ].join(' ')}
                      aria-pressed={intent === option.value}
                    >
                      <span className="flex items-center gap-2 font-medium">
                        {intent === option.value && <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />}
                        {option.label}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">{option.hint}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label htmlFor="message" className="mb-1 block text-sm font-medium">
                  Комментарий
                </label>
                <textarea
                  id="message"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  rows={3}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  placeholder="Например: хотим протестировать обучение для отдела продаж"
                />
              </div>

              <Button type="submit" className="w-full" disabled={loading || !canSubmit} aria-busy={loading}>
                {loading ? 'Создаем trial...' : 'Создать trial'}
              </Button>
            </form>

            <div className="mt-4 flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <Link href="/login" className="inline-flex items-center gap-1 text-primary hover:underline">
                <Mail className="h-4 w-4" aria-hidden="true" />
                Уже есть доступ
              </Link>
              <Link href="/register" className="text-primary hover:underline">
                Старый Telegram-flow
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
