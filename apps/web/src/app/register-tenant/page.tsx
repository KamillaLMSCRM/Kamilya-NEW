'use client';

import { FormEvent, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Building2, CheckCircle2, Mail, ShieldCheck, Sparkles } from 'lucide-react';

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { Logo } from '@/components/brand/Logo';
import { toast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { getRoleHome } from '@/lib/rolePolicy';
import { getTenantRegistrationError } from '@/lib/tenantRegistrationError';
import { formatKzPhone } from '@/lib/kzPhone';
import { extractTenantAttribution } from '@/lib/tenantAttribution';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useT } from '@/i18n/useT';
import { useLocaleQuery } from '@/i18n/useLocaleQuery';
import { useLanguageStore } from '@/store/languageStore';

type TenantIntent = 'try' | 'demo' | 'buy';

const employeeRanges = ['1-10', '11-50', '51-200', '201-1000', '1000+'];

export default function TenantRegisterPage() {
  useLocaleQuery();
  const router = useRouter();
  const { t } = useT();
  const lang = useLanguageStore((state) => state.lang);
  const login = useAuthStore((state) => state.login);
  const [companyName, setCompanyName] = useState('');
  const [contactName, setContactName] = useState('');
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [codeRequested, setCodeRequested] = useState(false);
  const [codeLoading, setCodeLoading] = useState(false);
  const [phone, setPhone] = useState('');
  const [telegramUsername, setTelegramUsername] = useState('');
  const [employeeCountRange, setEmployeeCountRange] = useState('');
  const [intent, setIntent] = useState<TenantIntent>('try');
  const [billingIdentifier, setBillingIdentifier] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const intentOptions: Array<{ value: TenantIntent; label: string; hint: string }> = [
    { value: 'try', label: t('publicUi.registration.intent.tryLabel'), hint: t('publicUi.registration.intent.tryHint') },
    { value: 'demo', label: t('publicUi.registration.intent.demoLabel'), hint: t('publicUi.registration.intent.demoHint') },
    { value: 'buy', label: t('publicUi.registration.intent.buyLabel'), hint: t('publicUi.registration.intent.buyHint') },
  ];

  function registrationErrorMessage(errorValue: any): string {
    if (lang === 'ru') return getTenantRegistrationError(errorValue);
    // Backend validation details are not a localized public contract and may
    // contain Russian implementation copy. Keep the selected UI language
    // coherent instead of leaking server text into KK/EN registration.
    return t('publicUi.registration.genericError');
  }

  const canSubmit = useMemo(() => {
    return companyName.trim().length >= 2
      && contactName.trim().length >= 2
      && email.trim().length > 3
      && codeRequested
      && /^\d{6}$/.test(emailCode)
      && privacyAccepted
      && termsAccepted;
  }, [companyName, contactName, email, emailCode, codeRequested, privacyAccepted, termsAccepted]);

  function handleEmailChange(value: string) {
    setEmail(value);
    setEmailCode('');
    setCodeRequested(false);
  }

  async function requestEmailCode() {
    const normalizedEmail = email.trim();
    if (!normalizedEmail || !normalizedEmail.includes('@')) {
      setError(t('publicUi.registration.validEmail'));
      return;
    }

    setError('');
    setCodeLoading(true);
    try {
      await api.post('/v1/tenants/register/request-code', { email: normalizedEmail });
      setCodeRequested(true);
      toast.success(t('publicUi.registration.codeSent'), {
        description: t('publicUi.registration.codeSentDescription'),
      });
    } catch (err: any) {
      const messageText = registrationErrorMessage(err);
      setError(messageText);
      toast.error(t('publicUi.registration.sendCodeError'), { description: messageText });
    } finally {
      setCodeLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');

    if (!canSubmit) {
      setError(t('publicUi.registration.requiredFields'));
      return;
    }

    setLoading(true);
    try {
      const attribution = extractTenantAttribution(window.location.search, document.referrer);
      const { data } = await api.post('/v1/tenants/register', {
        company_name: companyName.trim(),
        contact_name: contactName.trim(),
        email: email.trim(),
        email_code: emailCode,
        phone: phone.trim() || null,
        telegram_username: telegramUsername.trim() || null,
        employee_count_range: employeeCountRange || null,
        preferred_language: lang,
        intent,
        billing_identifier: billingIdentifier.trim() || null,
        message: message.trim() || null,
        privacy_consent_version: '2026-08-10',
        privacy_consent_locale: 'ru',
        privacy_consent_surface: 'tenant_registration',
        terms_version: '2026-08-10',
        ...attribution,
      });

      login(data.access_token, data.user);
      toast.success(t('publicUi.registration.trialCreated'), {
        description: t('publicUi.registration.trialCreatedDescription', { tenant: data.tenant_name }),
      });
      router.push(getRoleHome(data.user?.role));
    } catch (err: any) {
      const messageText = registrationErrorMessage(err);
      setError(messageText);
      toast.error(t('publicUi.registration.registrationError'), { description: messageText });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main-content" className="relative min-h-screen bg-background">
      <div className="absolute right-4 top-4 z-10">
        <LanguageSwitcher />
      </div>
      <div className="mx-auto grid min-h-screen w-full max-w-6xl grid-cols-1 gap-8 px-4 py-8 lg:grid-cols-[1fr_420px] lg:items-center lg:px-8">
        <section className="space-y-6">
          <div className="flex items-center gap-3">
            <Logo variant="full" size={44} />
            <Badge variant="outline">{t('publicUi.registration.trialBadge')}</Badge>
          </div>

          <div className="max-w-2xl space-y-4">
            <h1 className="text-3xl font-semibold leading-tight text-foreground md:text-4xl">
              {t('publicUi.registration.heroTitle')}
            </h1>
            <p className="text-base text-muted-foreground">
              {t('publicUi.registration.heroDescription')}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Card>
              <CardHeader className="p-4 pb-2">
                <Sparkles className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">{t('publicUi.registration.generationTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                {t('publicUi.registration.generationDescription')}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="p-4 pb-2">
                <ShieldCheck className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">{t('publicUi.registration.learnersTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                {t('publicUi.registration.learnersDescription')}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="p-4 pb-2">
                <Building2 className="h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-sm">{t('publicUi.registration.workspaceTitle')}</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-sm text-muted-foreground">
                {t('publicUi.registration.workspaceDescription')}
              </CardContent>
            </Card>
          </div>
        </section>

        <Card className="w-full">
          <CardHeader>
            <div className="flex items-center justify-between gap-4">
              <div>
                <CardTitle className="text-xl">{t('publicUi.registration.formTitle')}</CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t('publicUi.registration.formDescription')}
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
                  {t('publicUi.registration.company')}
                </label>
                <Input
                  id="company_name"
                  value={companyName}
                  onChange={(event) => setCompanyName(event.target.value)}
                  autoComplete="organization"
                  placeholder={t('publicUi.registration.companyPlaceholder')}
                  required
                  aria-required="true"
                />
              </div>

              <div>
                <label htmlFor="contact_name" className="mb-1 block text-sm font-medium">
                  <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                  {t('publicUi.registration.contact')}
                </label>
                <Input
                  id="contact_name"
                  value={contactName}
                  onChange={(event) => setContactName(event.target.value)}
                  autoComplete="name"
                  placeholder={t('publicUi.registration.contactPlaceholder')}
                  required
                  aria-required="true"
                />
              </div>

              <div>
                <div>
                  <label htmlFor="email" className="mb-1 block text-sm font-medium">
                    <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                    Email
                  </label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(event) => handleEmailChange(event.target.value)}
                    autoComplete="email"
                    placeholder="hr@company.kz"
                    required
                    aria-required="true"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-2 w-full"
                    onClick={requestEmailCode}
                    disabled={codeLoading || !email.trim().includes('@')}
                    aria-busy={codeLoading}
                  >
                    <Mail className="mr-2 h-4 w-4" aria-hidden="true" />
                    {codeLoading ? t('publicUi.registration.sending') : codeRequested ? t('publicUi.registration.resendCode') : t('publicUi.registration.getCode')}
                  </Button>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t('publicUi.registration.emailHelp')}
                  </p>
                </div>
              </div>

              {codeRequested && (
                <div>
                  <label htmlFor="email_code" className="mb-1 block text-sm font-medium">
                    <span aria-hidden="true" className="mr-0.5 text-destructive">*</span>
                    {t('publicUi.registration.code')}
                  </label>
                  <Input
                    id="email_code"
                    name="email-code"
                    value={emailCode}
                    onChange={(event) => setEmailCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    placeholder="000000"
                    required
                    aria-required="true"
                    aria-describedby="email-code-hint"
                  />
                  <p id="email-code-hint" className="mt-1 text-xs text-muted-foreground">
                    {t('publicUi.registration.codeHelp')}
                  </p>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="phone" className="mb-1 block text-sm font-medium">
                    {t('publicUi.registration.phone')}
                  </label>
                  <Input
                    id="phone"
                    value={phone}
                    onChange={(event) => setPhone(formatKzPhone(event.target.value))}
                    autoComplete="tel"
                    inputMode="tel"
                    placeholder="+7 (777) 000-00-00"
                    maxLength={18}
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
                    {t('publicUi.registration.companySize')}
                  </label>
                  <select
                    id="employees"
                    value={employeeCountRange}
                    onChange={(event) => setEmployeeCountRange(event.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  >
                    <option value="">{t('publicUi.registration.notSelected')}</option>
                    {employeeRanges.map((range) => (
                      <option key={range} value={range}>{range}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="billing_identifier" className="mb-1 block text-sm font-medium">
                    {t('publicUi.registration.billingId')}
                  </label>
                  <Input
                    id="billing_identifier"
                    value={billingIdentifier}
                    onChange={(event) => setBillingIdentifier(event.target.value)}
                    placeholder={t('publicUi.registration.optional')}
                  />
                </div>
              </div>

              <div>
                <span className="mb-2 block text-sm font-medium">{t('publicUi.registration.goal')}</span>
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
                  {t('publicUi.registration.comment')}
                </label>
                <textarea
                  id="message"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  rows={3}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                  placeholder={t('publicUi.registration.commentPlaceholder')}
                />
              </div>

              <fieldset className="space-y-3 rounded-md border border-input p-3">
                <legend className="px-1 text-sm font-medium">{t('publicUi.registration.confirmations')}</legend>
                <p className="text-xs text-muted-foreground">{t('publicUi.registration.legalLanguageNotice')}</p>
                <label htmlFor="privacy-acceptance" className="flex items-start gap-2 text-sm">
                  <input id="privacy-acceptance" type="checkbox" checked={privacyAccepted} onChange={(event) => setPrivacyAccepted(event.target.checked)} required aria-required="true" className="mt-1" />
                  <span><span aria-hidden="true" className="mr-1 text-destructive">*</span>{t('publicUi.registration.privacyBefore')} <Link href="/legal/privacy" className="text-primary underline">{t('publicUi.registration.privacyLink')}</Link>{t('publicUi.registration.privacyAfter')}</span>
                </label>
                <label htmlFor="terms-acceptance" className="flex items-start gap-2 text-sm">
                  <input id="terms-acceptance" type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} required aria-required="true" className="mt-1" />
                  <span><span aria-hidden="true" className="mr-1 text-destructive">*</span>{t('publicUi.registration.termsBefore')} <Link href="/legal/terms" className="text-primary underline">{t('publicUi.registration.termsLink')}</Link> {t('publicUi.registration.termsAfter')}</span>
                </label>
              </fieldset>

              <Button type="submit" className="w-full" disabled={loading || !canSubmit} aria-busy={loading}>
                {loading ? t('publicUi.registration.creating') : t('publicUi.registration.submit')}
              </Button>
            </form>

            <div className="mt-4 flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <Link href="/login" className="inline-flex items-center gap-1 text-primary hover:underline">
                <Mail className="h-4 w-4" aria-hidden="true" />
                {t('publicUi.registration.existingAccess')}
              </Link>
              <Link href="/login/demo" className="text-primary hover:underline">
                {t('publicUi.registration.sharedDemo')}
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
      <PublicLegalFooter />
    </main>
  );
}
