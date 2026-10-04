import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';

const { post, get, authState } = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), authState: { user: { role: 'methodologist', user_id: 'actor' }, accessToken: 'token' } }));
vi.mock('@/lib/api', () => ({ api: { post, get } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (state: any) => unknown) => selector(authState) }));

import AssignmentWorkbench from '@/features/methodologist-workbench/AssignmentWorkbench';
import { confirmAssignmentPlan, interpretAssignment, loadAssignmentPlan, requestAssignmentPreview } from '@/lib/methodologistWorkbench';
import { useLanguageStore } from '@/store/languageStore';

const ready = { state: 'preview_ready', plan_id: '11111111-1111-4111-8111-111111111111', revision: 2, fingerprint: 'a'.repeat(64), expires_at: '2026-12-31T00:00:00Z', course_id: '22222222-2222-4222-8222-222222222222', course_title: 'Safety', release_id: '33333333-3333-4333-8333-333333333333', department_id: '44444444-4444-4444-8444-444444444444', department_name: 'Operations', timezone_name: 'Asia/Almaty', due_at: '2026-12-31T17:59:59+05:00', notify: false, include_descendants: false, recipients: [{ user_id: '55555555-5555-4555-8555-555555555555', label: 'A', already_assigned: false, access_warning: false }], new_count: 1, skipped_count: 0 };
const command = 'Назначь курс "Safety" отделу "Operations" до 31.12.2026';
const enterCommand = () => fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: command } });

describe('AssignmentWorkbench', () => {
  beforeEach(() => { vi.resetAllMocks(); useLanguageStore.getState().setLang('ru'); window.history.replaceState(null, '', '/methodologist-workbench'); authState.user = { role: 'methodologist', user_id: 'actor' }; authState.accessToken = 'token'; vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true'); });

  it('starts blank and keeps preview transport disabled until a real command is entered', () => {
    render(<AssignmentWorkbench />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Рабочее место методиста');
    expect(screen.getByLabelText('Команда назначения')).toHaveAttribute('aria-describedby', 'assignment-command-example assignment-command-parser');
    expect(screen.getByRole('button', { name: 'Показать предварительный просмотр' })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it.each(['ru', 'kk', 'en'] as const)('renders accessible heading and purpose in %s', (locale) => {
    useLanguageStore.getState().setLang(locale);
    render(<AssignmentWorkbench />);
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/preview|алдын ала|предваритель/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Russian|орысша|русский/i)).toBeInTheDocument();
  });

  it('preserves a typed draft and accepted preview across locale switch', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: [], notification_state: 'not_requested' } });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    await act(async () => { useLanguageStore.getState().setLang('en'); });
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Methodologist workbench');
    expect(screen.getByLabelText('Assignment command')).toHaveValue(command);
    expect(screen.getByRole('button', { name: 'Confirm assignment' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm assignment' }));
    await waitFor(() => expect(screen.getByText('Assignment accepted')).toBeInTheDocument());
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('restores a plan under StrictMode effect replay instead of remaining pending', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockResolvedValue({ data: ready });
    render(<StrictMode><AssignmentWorkbench /></StrictMode>);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeEnabled());
    expect(post).not.toHaveBeenCalled();
  });

  it('preserves restored server options, ignores a late load after editing, and starts a safe new command', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockResolvedValueOnce({ data: { ...ready, timezone_name: 'UTC', notify: true, include_descendants: true } });
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    expect(screen.getByLabelText('Часовой пояс')).toHaveValue('UTC');
    expect(screen.getByLabelText('Уведомить получателей')).toBeChecked();
    expect(screen.getByLabelText('Включить дочерние отделы')).toBeChecked();
    expect(screen.getByRole('button', { name: 'Показать предварительный просмотр' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Новая команда' }));
    expect(window.location.search).toBe('');
    expect(screen.getByLabelText('Уведомить получателей')).not.toBeChecked();
    expect(screen.getByLabelText('Включить дочерние отделы')).not.toBeChecked();

    cleanup();
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    let resolvePlan!: (value: { data: typeof ready }) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { resolvePlan = resolve; }));
    render(<AssignmentWorkbench />);
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'new context' } });
    resolvePlan({ data: ready });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText('Проверьте назначение')).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('reloads an owned preview or receipt from the plan URL with GET only', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByText(/Восстановлен серверный план/)).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith(`/v1/methodologist-workbench/plans/${ready.plan_id}`, expect.anything());
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument();

    cleanup();
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: [ready.recipients[0].user_id], notification_state: 'not_requested' } });
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    expect(post).not.toHaveBeenCalled();
  });

  it('rejects an invalid plan URL without transport and clears it', async () => {
    window.history.replaceState(null, '', '/methodologist-workbench?plan=not-a-uuid');
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Invalid plan id'));
    expect(get).not.toHaveBeenCalled();
    expect(window.location.search).toBe('');
  });

  it.each(['404', '409'])('shows denied or expired plan read errors (%s) and clears the plan URL', async (status) => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    get.mockRejectedValueOnce(new Error(`Request failed with status code ${status}`));
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(status));
    expect(window.location.search).toBe('');
  });

  it('does not revive a late loaded plan after the authenticated session remounts', async () => {
    window.history.replaceState(null, '', `/methodologist-workbench?plan=${ready.plan_id}`);
    let resolvePlan!: (value: { data: typeof ready }) => void;
    get.mockReturnValueOnce(new Promise((resolve) => { resolvePlan = resolve; }));
    const view = render(<AssignmentWorkbench />);
    authState.accessToken = 'rotated-token';
    view.rerender(<AssignmentWorkbench />);
    resolvePlan({ data: ready });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText('Проверьте назначение')).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it('uses the explicit defaults and renders a validated preview before confirmation', async () => {
    post.mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />);
    expect(screen.getByLabelText('Команда назначения')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Показать предварительный просмотр' })).toBeDisabled();
    expect(screen.getByText('Asia/Almaty')).toBeInTheDocument();
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByText(/Safety \(22222222-2222-4222-8222-222222222222\)/)).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith('/v1/methodologist-workbench/assignment-preview', expect.objectContaining({ notify: false, include_descendants: false, timezone_name: 'Asia/Almaty' }));
  });

  it('confirms only after deliberate click and reports queued, not delivered', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [{ user_id: '55555555-5555-4555-8555-555555555555', enrollment_id: '88888888-8888-4888-8888-888888888888', notification_id: null }], skipped: [], notification_state: 'queued' } });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    expect(post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByText(/поставлены в очередь/)).toBeInTheDocument());
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/plans/11111111-1111-4111-8111-111111111111/confirm', { plan_id: '11111111-1111-4111-8111-111111111111', revision: 2, fingerprint: 'a'.repeat(64) });
    expect(window.location.search).toBe(`?plan=${ready.plan_id}`);
  });

  it('reloads the succeeded receipt after remount without issuing another confirmation', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: [ready.recipients[0].user_id], notification_state: 'not_requested' } });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    cleanup();
    get.mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: [ready.recipients[0].user_id], notification_state: 'not_requested' } });
    render(<AssignmentWorkbench />);
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith(`/v1/methodologist-workbench/plans/${ready.plan_id}`, expect.anything());
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('shows server clarification choices and resubmits selected ids', async () => {
    post.mockResolvedValueOnce({ data: { state: 'clarification_needed', code: 'ambiguous', course_choices: [{ id: '66666666-6666-4666-8666-666666666666', label: 'Safety' }], department_choices: [{ id: '77777777-7777-4777-8777-777777777777', label: 'Operations' }] } }).mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByText(/Не удалось однозначно подготовить назначение/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Курс'), { target: { value: '66666666-6666-4666-8666-666666666666' } });
    fireEvent.change(screen.getByLabelText('Отдел'), { target: { value: '77777777-7777-4777-8777-777777777777' } });
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByText(/Safety \(22222222-2222-4222-8222-222222222222\)/)).toBeInTheDocument());
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/assignment-preview', expect.objectContaining({ course_id: '66666666-6666-4666-8666-666666666666', department_id: '77777777-7777-4777-8777-777777777777' }));
  });

  it('uses the real transport seam for clarification, boolean warnings, and notification_state', async () => {
    const actual = await vi.importActual<typeof import('@/lib/methodologistWorkbench')>('@/lib/methodologistWorkbench');
    post.mockResolvedValueOnce({ data: { state: 'clarification_needed', code: 'ambiguous', course_choices: [{ id: '66666666-6666-4666-8666-666666666666', label: 'Safety' }], department_choices: [{ id: '77777777-7777-4777-8777-777777777777', label: 'Operations' }] } });
    const clarification = await actual.requestAssignmentPreview({ instruction: 'Назначь курс "Safety" отделу "Operations" до 31.12.2026', timezone_name: 'Asia/Almaty', notify: false, include_descendants: false });
    expect(clarification).toMatchObject({ state: 'clarification_needed', course_choices: [{ id: '66666666-6666-4666-8666-666666666666' }] });
    post.mockResolvedValueOnce({ data: ready });
    const parsed = await requestAssignmentPreview({ instruction: 'Назначь курс "Safety" отделу "Operations" до 31.12.2026', timezone_name: 'Asia/Almaty', notify: false, include_descendants: false });
    expect(parsed.state).toBe('preview_ready');
    expect((parsed as any).recipients[0].access_warning).toBe(false);
    post.mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [{ user_id: '55555555-5555-4555-8555-555555555555', enrollment_id: '88888888-8888-4888-8888-888888888888', notification_id: null }], skipped: [], notification_state: 'not_requested' } });
    const receipt = await actual.confirmAssignmentPlan(parsed as any);
    expect(receipt.notification_state).toBe('not_requested');
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/plans/11111111-1111-4111-8111-111111111111/confirm', { plan_id: ready.plan_id, revision: 2, fingerprint: 'a'.repeat(64) });
  });

  it('rejects forged transport state and binds GET readback to the requested plan', async () => {
    const actual = await vi.importActual<typeof import('@/lib/methodologistWorkbench')>('@/lib/methodologistWorkbench');
    const input = { instruction: 'Назначь курс "Safety" отделу "Operations" до 31.12.2026', timezone_name: 'Asia/Almaty', notify: false, include_descendants: false };
    for (const forged of [
      { ...ready, revision: 0 },
      { ...ready, fingerprint: 'A'.repeat(64) },
      { ...ready, due_at: '2026-12-31T17:59:59' },
      { ...ready, new_count: 0 },
      { ...ready, recipients: [ready.recipients[0], ready.recipients[0]] },
    ]) {
      post.mockResolvedValueOnce({ data: forged });
      await expect(actual.requestAssignmentPreview(input)).rejects.toThrow('Invalid assignment preview response');
    }
    get.mockResolvedValueOnce({ data: { ...ready, plan_id: '99999999-9999-4999-8999-999999999999' } });
    await expect(actual.loadAssignmentPlan(ready.plan_id)).rejects.toThrow('Plan identity mismatch');
  });

  it('rejects receipt user overlap and duplicate enrollment identities', async () => {
    const actual = await vi.importActual<typeof import('@/lib/methodologistWorkbench')>('@/lib/methodologistWorkbench');
    const malformed = [
      { state: 'succeeded', plan_id: ready.plan_id, created: [{ user_id: '55555555-5555-4555-8555-555555555555', enrollment_id: '88888888-8888-4888-8888-888888888888', notification_id: null }], skipped: ['55555555-5555-4555-8555-555555555555'], notification_state: 'queued' },
      { state: 'succeeded', plan_id: ready.plan_id, created: [{ user_id: '55555555-5555-4555-8555-555555555555', enrollment_id: '88888888-8888-4888-8888-888888888888', notification_id: null }, { user_id: '66666666-6666-4666-8666-666666666666', enrollment_id: '88888888-8888-4888-8888-888888888888', notification_id: null }], skipped: [], notification_state: 'queued' },
    ];
    for (const data of malformed) {
      post.mockResolvedValueOnce({ data });
      await expect(actual.confirmAssignmentPlan(ready as any)).rejects.toThrow(/Invalid receipt identities/);
    }
  });

  it('does not revive a late preview after context change and prevents rapid double confirmation', async () => {
    let resolvePreview!: (value: { data: typeof ready }) => void;
    post.mockReturnValueOnce(new Promise((resolve) => { resolvePreview = resolve; }));
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'changed' } });
    resolvePreview({ data: ready });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText('Проверьте назначение')).not.toBeInTheDocument();

    cleanup();
    post.mockReset();
    post.mockResolvedValueOnce({ data: ready });
    let resolveReceipt!: (value: { data: unknown }) => void;
    post.mockReturnValueOnce(new Promise((resolve) => { resolveReceipt = resolve; }));
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    const confirmButton = screen.getByRole('button', { name: 'Подтвердить назначение' });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);
    expect(post).toHaveBeenCalledTimes(2);
    resolveReceipt({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: ['55555555-5555-4555-8555-555555555555'], notification_state: 'not_requested' } });
  });

  it('clears selected clarification IDs when instruction/context changes', async () => {
    post.mockResolvedValueOnce({ data: { state: 'clarification_needed', code: 'ambiguous', course_choices: [{ id: '66666666-6666-4666-8666-666666666666', label: 'Safety' }], department_choices: [{ id: '77777777-7777-4777-8777-777777777777', label: 'Operations' }] } }).mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByLabelText('Курс')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Курс'), { target: { value: '66666666-6666-4666-8666-666666666666' } });
    fireEvent.change(screen.getByLabelText('Отдел'), { target: { value: '77777777-7777-4777-8777-777777777777' } });
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'new instruction' } });
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByText(/Safety \(22222222-2222-4222-8222-222222222222\)/)).toBeInTheDocument());
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/assignment-preview', expect.not.objectContaining({ course_id: expect.anything(), department_id: expect.anything() }));
  });

  it('removes receipt and pending state when session identity or active role changes', async () => {
    post.mockResolvedValueOnce({ data: ready }).mockResolvedValueOnce({ data: { state: 'succeeded', plan_id: ready.plan_id, created: [], skipped: ['55555555-5555-4555-8555-555555555555'], notification_state: 'not_requested' } });
    const view = render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить назначение' }));
    await waitFor(() => expect(screen.getByText('Назначение принято')).toBeInTheDocument());
    authState.accessToken = 'rotated-token';
    view.rerender(<AssignmentWorkbench />);
    expect(screen.queryByText('Назначение принято')).not.toBeInTheDocument();
    authState.user = { role: 'admin', user_id: 'actor' };
    view.rerender(<AssignmentWorkbench />);
    expect(screen.getByText('Доступ только для методолога.')).toBeInTheDocument();
    expect(screen.queryByText('Назначение принято')).not.toBeInTheDocument();
  });

  it('turns unsupported parser codes into actionable Russian guidance without exposing the code', async () => {
    post.mockResolvedValueOnce({ data: { state: 'clarification_needed', code: 'instruction_unsupported', course_choices: [], department_choices: [] } });
    render(<AssignmentWorkbench />);
    enterCommand();
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByText(/Команда не распознана/)).toBeInTheDocument());
    expect(screen.queryByText('instruction_unsupported')).not.toBeInTheDocument();
    expect(screen.getByText(/ДД\.ММ\.ГГГГ/)).toBeInTheDocument();
  });

  it('keeps natural interpretation explicit and sends the edited candidate only at preview', async () => {
    post.mockResolvedValueOnce({ data: { state: 'interpreted', candidate: { course_query: 'Safety', department_query: 'Operations', due_date: '2026-12-31', due_time: '23:59:59', notify: true, include_descendants: false } } }).mockResolvedValueOnce({ data: ready });
    render(<AssignmentWorkbench />);
    fireEvent.click(screen.getByRole('button', { name: 'Свободное описание' }));
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'Назначить обучение по безопасности операционному отделу к концу года' } });
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByDisplayValue('Safety')).toBeInTheDocument());
    fireEvent.change(screen.getByDisplayValue('Safety'), { target: { value: 'Safety v2' } });
    fireEvent.change(screen.getByLabelText('Время'), { target: { value: '09:30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить назначение' })).toBeInTheDocument());
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/assignment-preview', expect.objectContaining({ candidate: expect.objectContaining({ course_query: 'Safety v2', due_time: '09:30:00', notify: true }), notify: true, include_descendants: false }));
  });

  it('rejects interpretation candidates outside the frozen transport shape', async () => {
    const actual = await vi.importActual<typeof import('@/lib/methodologistWorkbench')>('@/lib/methodologistWorkbench');
    post.mockResolvedValueOnce({ data: { state: 'interpreted', candidate: { course_query: 'Safety', department_query: 'Operations', due_date: '2026-12-31', due_time: '23:59:59', notify: false, include_descendants: false, plan_id: ready.plan_id } } });
    await expect(actual.interpretAssignment('assign safety', 'Asia/Almaty', false, false)).rejects.toThrow(/Invalid assignment/);
  });

  it.each([
    { course_query: ' ' }, { department_query: 'x'.repeat(301) },
    { due_date: '' }, { due_date: '2026-02-30' },
    { due_time: '' }, { due_time: '24:00:00' }, { due_time: '09:60:00' },
  ])('rejects an incomplete or invalid editable candidate: %j', async (invalid) => {
    const actual = await vi.importActual<typeof import('@/lib/methodologistWorkbench')>('@/lib/methodologistWorkbench');
    expect(actual.isAssignmentCandidate({ course_query: 'Safety', department_query: 'Operations', due_date: '2026-12-31', due_time: '23:59:59', notify: false, include_descendants: false, ...invalid })).toBe(false);
  });

  it('transitions ready preview into an editable correction before reinterpreting with its owned plan', async () => {
    const interpreted = { state: 'interpreted', candidate: { course_query: 'Safety', department_query: 'Operations', due_date: '2026-12-31', due_time: '23:59:59', notify: false, include_descendants: false } };
    post.mockResolvedValueOnce({ data: interpreted }).mockResolvedValueOnce({ data: ready }).mockResolvedValueOnce({ data: interpreted });
    render(<AssignmentWorkbench />);
    fireEvent.click(screen.getByRole('button', { name: 'Свободное описание' }));
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'assign safety' } });
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByDisplayValue('Safety')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Показать предварительный просмотр' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Уточнить поручение' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Уточнить поручение' }));
    expect(screen.getByLabelText('Команда назначения')).toHaveValue('');
    expect(screen.queryByDisplayValue('Safety')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'assign safety by next Friday' } });
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getAllByDisplayValue('Safety').length).toBeGreaterThan(0));
    expect(post).toHaveBeenLastCalledWith('/v1/methodologist-workbench/interpret-assignment', expect.objectContaining({ instruction: 'assign safety by next Friday', previous_plan_id: ready.plan_id }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it('clears an interpreted candidate on failure and aborts the superseded request', async () => {
    let rejectInterpret!: (cause: Error) => void;
    post.mockReturnValueOnce(Promise.resolve({ data: { state: 'interpreted', candidate: { course_query: 'Safety', department_query: 'Operations', due_date: '2026-12-31', due_time: '23:59:59', notify: true, include_descendants: false } } }));
    render(<AssignmentWorkbench />);
    fireEvent.click(screen.getByRole('button', { name: 'Свободное описание' }));
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'assign safety' } });
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    await waitFor(() => expect(screen.getByDisplayValue('Safety')).toBeInTheDocument());
    post.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectInterpret = reject; }));
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'new request' } });
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать поручение' }));
    const signal = post.mock.calls[1][2]?.signal as AbortSignal | undefined;
    expect(signal).toBeInstanceOf(AbortSignal);
    fireEvent.change(screen.getByLabelText('Команда назначения'), { target: { value: 'edited request' } });
    expect(signal?.aborted).toBe(true);
    rejectInterpret(new Error('provider unavailable'));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByDisplayValue('Safety')).not.toBeInTheDocument();
  });
});
