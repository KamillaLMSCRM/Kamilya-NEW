import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const freezeMock = vi.hoisted(() => vi.fn());
const createMock = vi.hoisted(() => vi.fn());
const writeTextMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { get: getMock } }));
vi.mock('@/lib/courseApproval', () => ({ freezeApprovalRevision: freezeMock, createApprovalRequest: createMock }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ApprovalRequestModal } from '@/components/course-approval/ApprovalRequestModal';

let execCommandMock: ReturnType<typeof vi.fn>;
let originalExecCommandDescriptor: PropertyDescriptor | undefined;

const credentials = [
  { reviewer_id: 'reviewer-1', access_url: 'https://example.test/review/one', temporary_pin: '123456', expires_at: '2027-01-01T00:00:00Z' },
  { reviewer_id: 'reviewer-2', access_url: 'https://example.test/review/two', temporary_pin: '654321', expires_at: '2027-01-01T00:00:00Z' },
];

describe('approval credential reveal', () => {
  beforeEach(() => {
    originalExecCommandDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand');
    getMock.mockReset().mockResolvedValue({ data: [] });
    freezeMock.mockReset().mockResolvedValue({ id: 'revision-1' });
    createMock.mockReset().mockResolvedValue({ request_id: 'request-1', revision_id: 'revision-1', outcome: 'pending', delivery_mode: 'personal_link', access_credentials: credentials });
    writeTextMock.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: writeTextMock } });
    execCommandMock = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommandMock });
  });

  afterEach(() => {
    if (originalExecCommandDescriptor) Object.defineProperty(document, 'execCommand', originalExecCommandDescriptor);
    else Reflect.deleteProperty(document, 'execCommand');
    originalExecCommandDescriptor = undefined;
  });

  it('reveals every newly issued credential ephemerally with independent URL and PIN actions', async () => {
    const onClose = vi.fn();
    render(<ApprovalRequestModal open courseId="course-1" onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Guest One' } });
    fireEvent.change(screen.getByLabelText('Email гостя'), { target: { value: 'one@example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить гостя' }));
    fireEvent.click(screen.getByLabelText('Ссылка и PIN'));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    await waitFor(() => expect(screen.getByText('https://example.test/review/one')).toBeInTheDocument());
    expect(screen.getByText('https://example.test/review/two')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Скопировать ссылку' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: 'Скопировать PIN' })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole('button', { name: 'Скопировать ссылку' })[0]);
    fireEvent.click(screen.getAllByRole('button', { name: 'Скопировать PIN' })[0]);
    expect(writeTextMock).toHaveBeenNthCalledWith(1, 'https://example.test/review/one');
    expect(writeTextMock).toHaveBeenNthCalledWith(2, '123456');
    fireEvent.click(screen.getByRole('button', { name: 'Я скопировал данные — закрыть' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('https://example.test/review/one')).not.toBeInTheDocument();
    expect(screen.queryByText('123456')).not.toBeInTheDocument();
  });

  it('reports clipboard failure while attempting the manual fallback', async () => {
    writeTextMock.mockRejectedValue(new Error('blocked'));
    execCommandMock.mockReturnValue(false);
    render(<ApprovalRequestModal open courseId="course-1" onClose={() => undefined} />);
    fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Guest One' } });
    fireEvent.change(screen.getByLabelText('Email гостя'), { target: { value: 'one@example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить гостя' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Скопировать ссылку' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать ссылку' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/не удалось скопировать/i);
  });
});
