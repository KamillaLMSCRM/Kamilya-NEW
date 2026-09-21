import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LocaleDocumentSync } from '@/components/LocaleDocumentSync';
import LoginPage from '@/app/login/page';
import DemoLoginPage from '@/app/login/demo/page';
import TenantRegisterPage from '@/app/register-tenant/page';
import { useLanguageStore } from '@/store/languageStore';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));
const loginMock = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({ api: apiMock }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: Object.assign(
    (selector?: (state: { login: typeof loginMock; accessToken: null }) => unknown) => {
      const state = { login: loginMock, accessToken: null };
      return selector ? selector(state) : state;
    },
    { getState: () => ({ user: null }) },
  ),
}));

function leafKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    leafKeys(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe('public locale contract', () => {
  beforeEach(() => {
    apiMock.get.mockReset();
    apiMock.post.mockReset();
    apiMock.get.mockResolvedValue({ data: { telegram_login_enabled: false } });
    loginMock.mockReset();
    useLanguageStore.setState({ lang: 'ru' });
    document.documentElement.lang = 'ru';
    window.history.replaceState({}, '', '/login');
  });

  it('keeps the public UI locale namespace identical in every locale', () => {
    const locales = ['ru', 'kk', 'en'].map((locale) => JSON.parse(
      readFileSync(resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8'),
    ));
    const expected = leafKeys(locales[0].publicUi).sort();

    expect(leafKeys(locales[1].publicUi).sort()).toEqual(expected);
    expect(leafKeys(locales[2].publicUi).sort()).toEqual(expected);
  });

  it('switches language before authentication and remains available in the authenticated shell', () => {
    apiMock.get.mockReturnValue(new Promise(() => undefined));
    const files = [
      'src/app/login/page.tsx',
      'src/app/superadmin/login/page.tsx',
      'src/app/register-tenant/page.tsx',
      'src/app/accept-invite/page.tsx',
      'src/app/access/[token]/page.tsx',
      'src/components/legal/LegalDocument.tsx',
    ];

    for (const file of files) {
      expect(readFileSync(resolve(process.cwd(), file), 'utf8'), file).toContain('<LanguageSwitcher');
    }
    expect(
      readFileSync(resolve(process.cwd(), 'src/components/layout/TopBar.tsx'), 'utf8'),
    ).toContain('<LanguageSwitcher />');

    render(<LoginPage />);
    const selector = screen.getByRole('combobox', { name: 'Выбрать язык интерфейса' });
    fireEvent.change(selector, { target: { value: 'en' } });
    expect(screen.getByRole('heading', { name: 'Sign in to Kamilya LMS' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Select interface language' })).toHaveValue('en');
  });

  it('honours the language passed from a localized landing page', async () => {
    apiMock.get.mockReturnValue(new Promise(() => undefined));
    window.history.replaceState({}, '', '/login?lang=en');

    render(<LoginPage />);

    expect(await screen.findByRole('heading', { name: 'Sign in to Kamilya LMS' })).toBeInTheDocument();
    expect(useLanguageStore.getState().lang).toBe('en');
  });

  it('honours a direct language parameter on the public demo-role page', async () => {
    window.history.replaceState({}, '', '/login/demo?lang=en');

    render(<DemoLoginPage />);

    expect(await screen.findByRole('heading', { name: 'Demo access' })).toBeInTheDocument();
    expect(useLanguageStore.getState().lang).toBe('en');
    expect(screen.getByRole('link', { name: 'Back to sign in' })).toHaveAttribute(
      'href',
      '/login?lang=en',
    );
    expect(screen.getByRole('link', { name: 'Create a separate trial for your company' })).toHaveAttribute(
      'href',
      '/register-tenant?lang=en',
    );
  });

  it('ignores an unsupported cross-site language value', async () => {
    apiMock.get.mockReturnValue(new Promise(() => undefined));
    window.history.replaceState({}, '', '/login?lang=de');

    render(<LoginPage />);

    expect(await screen.findByRole('heading', { name: 'Вход в Kamilya LMS' })).toBeInTheDocument();
    expect(useLanguageStore.getState().lang).toBe('ru');
  });

  it('synchronizes the document language with the selected locale', async () => {
    render(<LocaleDocumentSync />);

    act(() => useLanguageStore.getState().setLang('en'));
    await waitFor(() => expect(document.documentElement).toHaveAttribute('lang', 'en'));

    act(() => useLanguageStore.getState().setLang('kk'));
    await waitFor(() => expect(document.documentElement).toHaveAttribute('lang', 'kk'));
  });

  it('submits the selected preferred language and preserves Russian consent evidence', async () => {
    useLanguageStore.setState({ lang: 'en' });
    apiMock.post
      .mockResolvedValueOnce({ data: { ok: true } })
      .mockResolvedValueOnce({
        data: {
          access_token: 'access-token',
          user: { role: 'methodologist' },
          tenant_name: 'Example Company',
        },
      });

    render(<TenantRegisterPage />);

    fireEvent.change(screen.getByLabelText(/Company$/), { target: { value: 'Example Company' } });
    fireEvent.change(screen.getByLabelText(/Contact person$/), { target: { value: 'Alex Example' } });
    fireEvent.change(screen.getByLabelText(/Email$/), { target: { value: 'alex@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get code' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/v1/tenants/register/request-code',
      { email: 'alex@example.com' },
    ));

    fireEvent.change(await screen.findByLabelText(/Code from email$/), { target: { value: '123456' } });
    fireEvent.click(screen.getByLabelText(/I consent to personal-data processing/i));
    fireEvent.click(screen.getByLabelText(/On behalf of the organisation/i));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm email and create trial' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenLastCalledWith(
      '/v1/tenants/register',
      expect.objectContaining({
        preferred_language: 'en',
        privacy_consent_locale: 'ru',
        privacy_consent_version: '2026-08-10',
      }),
    ));
  });

  it('does not leak unlocalized backend detail into English registration', async () => {
    useLanguageStore.setState({ lang: 'en' });
    apiMock.post.mockRejectedValueOnce({
      response: { data: { detail: 'Не удалось отправить код' } },
    });

    render(<TenantRegisterPage />);
    fireEvent.change(screen.getByLabelText(/Email$/), { target: { value: 'alex@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get code' }));

    expect(await screen.findByText(
      'Could not create the trial. Check the form and try again.',
    )).toBeInTheDocument();
    expect(screen.queryByText('Не удалось отправить код')).not.toBeInTheDocument();
  });
});
