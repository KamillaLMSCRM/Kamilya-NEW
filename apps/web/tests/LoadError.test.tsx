import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LoadError } from '@/components/ui/LoadError';

describe('LoadError', () => {
  it('keeps the failure visible and retries on demand', () => {
    const onRetry = vi.fn();
    render(
      <LoadError
        title="Не удалось загрузить"
        message="Сервис временно недоступен"
        retryLabel="Повторить"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
