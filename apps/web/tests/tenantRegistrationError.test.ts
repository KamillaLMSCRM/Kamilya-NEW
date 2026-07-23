import { describe, expect, it } from 'vitest';

import { getTenantRegistrationError } from '@/lib/tenantRegistrationError';

describe('getTenantRegistrationError', () => {
  it('renders FastAPI validation details with a human field label', () => {
    const error = {
      response: {
        data: {
          detail: [
            {
              loc: ['body', 'email'],
              msg: 'value is not a valid email address',
            },
          ],
        },
      },
    };

    expect(getTenantRegistrationError(error)).toBe(
      'Email: value is not a valid email address',
    );
  });

  it('does not expose the generic Axios status text', () => {
    expect(
      getTenantRegistrationError({
        message: 'Request failed with status code 500',
      }),
    ).toBe('Не удалось создать trial. Проверьте поля формы и попробуйте ещё раз.');
  });
});
