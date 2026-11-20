import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { TelegramSubscription, TELEGRAM_LEARNING_API } from '@/features/learning-notifications/TelegramSubscription';
import { TelegramDeliveryLine } from '@/features/learning-notifications/TelegramStatus';

const { get, post, del } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), del: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { get, post, delete: del } }));

beforeEach(() => {
  vi.resetAllMocks();
});

it('links and disconnects the current profile while keeping the email channel visible', async () => {
  const disconnected = { available: true, connected: false, pending_confirmation: false };
  get.mockResolvedValue({ data: disconnected });
  post.mockResolvedValueOnce({ data: { url: 'https://t.me/SyntheticBot?start=fixture' } })
    .mockResolvedValueOnce({ data: { ...disconnected, connected: true } });
  del.mockResolvedValue({ data: disconnected });
  render(<TelegramSubscription />);
  fireEvent.click(await screen.findByRole('button', { name: 'Подключить Telegram' }));
  expect(await screen.findByRole('link', { name: /Открыть бота/ })).toHaveAttribute('href', 'https://t.me/SyntheticBot?start=fixture');
  const submit = screen.getByRole('button', { name: 'Подтвердить' });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Код из сообщения бота'), { target: { value: '012345ABCDEF' } });
  fireEvent.click(submit);
  expect(post).toHaveBeenLastCalledWith(`${TELEGRAM_LEARNING_API}/subscription/confirm`, { code: '012345ABCDEF' });
  expect(await screen.findByText('Telegram подключён')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Отключить Telegram' }));
  expect(del).toHaveBeenCalledWith(`${TELEGRAM_LEARNING_API}/subscription`);
  expect(await screen.findByText('Telegram не подключён')).toBeVisible();
  expect(screen.getByText('Почтовые уведомления продолжают приходить.')).toBeVisible();
});

it('shows uncertain delivery without treating it as sent', () => {
  render(<TelegramDeliveryLine delivery={{
    id: 'fixture', step: 'before_due', status: 'uncertain', reason: 'delivery_uncertain',
    scheduled_at: '2026-11-20T04:00:00Z', sent_at: null,
  }} />);
  expect(screen.getByText(/Telegram · Напоминание о сроке · Отправка не подтверждена/)).toBeVisible();
  expect(screen.queryByText(/Telegram принял сообщение/)).not.toBeInTheDocument();
});
