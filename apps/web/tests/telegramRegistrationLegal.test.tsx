import { beforeEach, describe, expect, it, vi } from 'vitest';

const redirect = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({ redirect }));

import RegisterPage from '@/app/register/page';

describe('legacy Telegram registration route', () => {
  beforeEach(() => redirect.mockReset());

  it('redirects to the current email-first tenant registration', () => {
    RegisterPage();

    expect(redirect).toHaveBeenCalledOnce();
    expect(redirect).toHaveBeenCalledWith('/register-tenant');
  });
});
