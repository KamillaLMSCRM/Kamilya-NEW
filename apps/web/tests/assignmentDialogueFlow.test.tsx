import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const { post, get, auth } = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), auth: { user: { role: 'methodologist', user_id: 'actor', tenant_id: 'tenant-a' }, accessToken: 'token' } }));
vi.mock('@/lib/api', () => ({ api: { post, get } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (value: any) => unknown) => selector(auth) }));
import AssignmentWorkbench from '@/features/methodologist-workbench/AssignmentWorkbench';
import { useLanguageStore } from '@/store/languageStore';

const candidate = { course_query: 'Safety', department_query: 'Operations', due_date: '2030-12-31', due_time: '18:00:00', notify: false, include_descendants: false };
const ready = { state: 'preview_ready', plan_id: '11111111-1111-4111-8111-111111111111', revision: 1, fingerprint: 'a'.repeat(64), expires_at: '2030-12-30T00:00:00Z', course_id: '22222222-2222-4222-8222-222222222222', course_title: 'Safety', release_id: '33333333-3333-4333-8333-333333333333', department_id: '44444444-4444-4444-8444-444444444444', department_name: 'Operations', timezone_name: 'Asia/Almaty', due_at: '2030-12-31T13:00:00Z', notify: false, include_descendants: false, recipients: [{ user_id: '55555555-5555-4555-8555-555555555555', label: 'QA', already_assigned: false, access_warning: false }], new_count: 1, skipped_count: 0 };
const receipt = { state: 'succeeded', plan_id: ready.plan_id, course_id: ready.course_id, created: [{ user_id: ready.recipients[0].user_id, enrollment_id: '66666666-6666-4666-8666-666666666666', notification_id: null }], skipped: [], notification_state: 'not_requested' };
const type = (value: string) => fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value } });
const open = () => { render(<AssignmentWorkbench />); fireEvent.click(screen.getByRole('button', { name: 'Свободное описание' })); };

describe('assignment dialogue integration', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true'); useLanguageStore.getState().setLang('ru'); window.history.replaceState(null, '', '/methodologist-workbench'); auth.user.tenant_id = 'tenant-a'; });
  it('retains an incomplete request for the next explicit turn, never auto-confirms', async () => {
    post.mockResolvedValueOnce({ data: { state: 'clarification_needed', code: 'intent_clarification', course_choices: [], department_choices: [] } }).mockResolvedValueOnce({ data: { state: 'interpreted', candidate } });
    open(); type('Подготовь назначение курса Safety');
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('log', { name: 'Диалог назначения' })).toHaveTextContent('Подготовь назначение курса Safety'));
    type('Отдел Operations, до 31 декабря 2030 года');
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByLabelText('Курс')).toHaveValue('Safety'));
    expect(post.mock.calls[1][1].instruction_history).toEqual(['Подготовь назначение курса Safety']);
    expect(post.mock.calls.every(([url]) => !url.endsWith('/confirm'))).toBe(true);
  });
  it('maps a rejected preview safely and keeps the command for correction', async () => {
    post.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 409'), {
      response: { status: 409, data: { error: 'conflict', message: 'audience_empty' } },
    }));
    render(<AssignmentWorkbench />);
    const instruction = 'Назначь курс "Safety" отделу "Operations" до 31.12.2030';
    type(instruction);
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('В выбранном отделе нет подходящих активных сотрудников'));
    expect(screen.getByLabelText('Команда назначения')).toHaveValue(instruction);
    expect(screen.queryByText('Request failed with status code 409')).not.toBeInTheDocument();
    expect(screen.queryByText('audience_empty')).not.toBeInTheDocument();
  });
  it('uses a safe generic message for an unknown preview rejection', async () => {
    post.mockRejectedValueOnce(Object.assign(new Error('provider secret'), {
      response: { status: 409, data: { error: 'conflict', message: 'unknown_provider_code' } },
    }));
    render(<AssignmentWorkbench />);
    type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Не удалось однозначно подготовить назначение'));
    expect(screen.queryByText('provider secret')).not.toBeInTheDocument();
    expect(screen.queryByText('unknown_provider_code')).not.toBeInTheDocument();
  });
  it('keeps unknown confirmation locked and restores the same receipt by GET', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(new Error('Network lost'));
    get.mockResolvedValueOnce({ data: receipt });
    render(<AssignmentWorkbench />); type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    expect(screen.getByLabelText('Команда назначения')).toBeDisabled();
    expect(window.location.search).toBe(`?plan=${ready.plan_id}&confirming=1`);
    fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith(`/v1/methodologist-workbench/plans/${ready.plan_id}`, undefined);
    expect(post).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('link', { name: 'Открыть назначения курса' })).toHaveAttribute('href', `/assignments?course_id=${ready.course_id}`);
  });
  it('restores course navigation from a receipt on reload without POST', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockResolvedValueOnce({ data: receipt }); render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Открыть назначения курса' })).toBeInTheDocument());
    expect(post).not.toHaveBeenCalled();
  });
  it('a typed expired409 is a rejection, not a permanently locked unknown result', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(Object.assign(new Error('expired'), { response: { status: 409, data: { detail: 'expired' } } }));
    render(<AssignmentWorkbench />); type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Срок плана истёк или он изменился'));
    expect(screen.queryByText('expired')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Команда назначения')).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Проверить результат' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Новая команда' })).toBeEnabled();
  });
  it('accepts the canonical conflict envelope for a known definitive 409', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 409'), {
      response: { status: 409, data: { error: 'conflict', message: 'expired' } },
    }));
    render(<AssignmentWorkbench />); type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Срок плана истёк или он изменился'));
    expect(screen.queryByText('Request failed with status code 409')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Команда назначения')).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Проверить результат' })).not.toBeInTheDocument();
  });
  it('keeps an unknown canonical 409 locked for same-plan recovery', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(Object.assign(new Error('provider conflict'), {
      response: { status: 409, data: { error: 'conflict', message: 'unknown_provider_code' } },
    }));
    get.mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />); type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    expect(screen.getByLabelText('Команда назначения')).toBeDisabled();
    expect(window.location.search).toContain('confirming=1');
    expect(screen.queryByText('provider conflict')).not.toBeInTheDocument();
    expect(screen.queryByText('unknown_provider_code')).not.toBeInTheDocument();
  });
  it('ready GET after a lost-confirm reload must not unlock replacement', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}&confirming=1`);
    get.mockResolvedValueOnce({ data: ready }); render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Новая команда' })).toBeDisabled();
    expect(screen.getByLabelText('Команда назначения')).toBeDisabled();
    expect(window.location.search).toContain('confirming=1');
    expect(post).not.toHaveBeenCalled();
  });
  it('receipt GET after confirm reload removes only its recovery marker', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}&confirming=1`);
    get.mockResolvedValueOnce({ data: receipt }); render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    expect(window.location.search).toBe(`?plan=${ready.plan_id}`);
    expect(post).not.toHaveBeenCalled();
  });
  it('drops user history and late interpretation on language or tenant context change', async () => {
    let resolve!: (value: unknown) => void;
    post.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    open(); type('Old request'); fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await act(async () => { useLanguageStore.getState().setLang('en'); });
    await act(async () => { resolve({ data: { state: 'interpreted', candidate } }); });
    expect(screen.queryByDisplayValue('Safety')).not.toBeInTheDocument();
    expect(screen.queryByText('Old request')).not.toBeInTheDocument();
    cleanup();
  });
  it('preserves a long one-shot instruction but does not silently truncate it into history', async () => {
    post.mockResolvedValueOnce({ data: { state: 'interpreted', candidate } });
    open(); type('x'.repeat(2500)); fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByLabelText('Курс')).toHaveValue('Safety'));
    expect(post.mock.calls[0][1].instruction).toHaveLength(2500);
    expect(post.mock.calls[0][1].instruction_history).toBeUndefined();
    type('Change only the deadline'); fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Поручение длиннее 2000 символов принято целиком');
  });
  it('unknown409 stays locked and a same-ID ready recovery does not unlock replacement', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(Object.assign(new Error('unknown'), { response: { status: 409, data: { detail: 'unrecognized_proxy_conflict' } } }));
    get.mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />); type('Назначь курс "Safety" отделу "Operations" до 31.12.2030');
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('Команда назначения')).toBeDisabled();
    expect(window.location.search).toContain('confirming=1');
    expect(post).toHaveBeenCalledTimes(2);
  });
  it('locale clears dialogue text but retains unknown confirmation locator and seal', async () => {
    post.mockResolvedValueOnce({ data: { state: 'interpreted', candidate } }).mockResolvedValueOnce({ data: ready }).mockRejectedValueOnce(new Error('Network lost'));
    open(); type('Private old-language text'); fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByLabelText('Курс')).toHaveValue('Safety'));
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    await act(async () => { useLanguageStore.getState().setLang('en'); });
    expect(screen.queryByText('Private old-language text')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Assignment command')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Check result' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'New command' })).toBeDisabled();
    expect(window.location.search).toContain('confirming=1');
  });
  it('a failed confirmation restore preserves its URL and exposes same-ID read retry', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}&confirming=1`);
    get.mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce({ data: receipt });
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить результат' })).toBeEnabled());
    expect(window.location.search).toContain('confirming=1');
    expect(screen.getByLabelText('Команда назначения')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    expect(post).not.toHaveBeenCalled();
  });
});
