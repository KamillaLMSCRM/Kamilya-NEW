import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceActualityPanel } from '@/features/source-actuality/SourceActualityPanel';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));

const ownerId = '5187fa5f-c046-4e35-945e-5c95f469a886';
const family = {
  source_family_id: '9be88b82-12a5-4363-91a8-76db81fb149f',
  latest_document_id: '08c75880-bc87-443b-92d3-ea9cde5cd617',
  latest_version: 1, title: 'Synthetic policy source', filename: 'policy.txt',
  actuality_state: 'unassigned', owner_id: null, owner_name: null,
  reviewed_at: null, next_review_at: null, pending_review_id: null, pending_review_status: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  useLanguageStore.setState({ lang: 'ru' });
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/users?')
    ? { users: [{ id: ownerId, first_name: 'Тестовый', last_name: 'методист', role: 'methodologist', is_active: true }], total: 1 }
    : { items: [family] } }) as never);
  vi.mocked(api.put).mockResolvedValue({ data: {} });
});

describe('source owner policy actions', () => {
  it('opens the exact updated lesson from the decision receipt and after reload', async () => {
    const reviewPath = '/v1/admin/source-actuality/reviews/updated-review';
    const updatedFamily = { ...family, latest_version: 2, pending_review_id: 'updated-review' };
    const analysis = {
      id: 'updated-review', status: 'ready',
      added_fact_count: 1, removed_fact_count: 1, changed_fact_count: 0,
      impacted_course_count: 1, impacted_lesson_count: 1, assessment_questions_requiring_review: 1,
      added_facts: [], removed_facts: [], changed_facts: [], analysis_truncated: false,
      impacted_courses: [{
        course_id: 'old-course', title: 'Правила хранения', active_enrollments: 1, completed_enrollments: 2,
        assessment_questions_requiring_review: 1, impacted_lesson_ids: ['old-lesson'],
        impacted_lessons: [{ lesson_id: 'old-lesson', title: 'Срок хранения' }],
      }],
    };
    const receipt = {
      ...analysis, status: 'resolved', decision: 'update_future',
      decision_snapshot: {
        draft_courses: [{
          course_id: 'new-course', title: 'Правила хранения',
          lessons: [{ lesson_id: 'new-lesson', title: 'Срок хранения' }],
        }],
      },
    };
    let resolved = false;
    vi.mocked(api.get).mockImplementation(async url => ({
      data: url === reviewPath ? (resolved ? receipt : analysis) : String(url).startsWith('/v1/users?')
        ? { users: [], total: 0 } : { items: [updatedFamily] },
    }) as never);
    vi.mocked(api.post).mockImplementation(async () => {
      resolved = true;
      return { data: receipt } as never;
    });
    const view = render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть анализ версии' }));
    expect(await screen.findByText('Срок хранения')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Решение'), { target: { value: 'update_future' } });
    fireEvent.change(screen.getByLabelText('Обоснование (не менее 20 символов)'), {
      target: { value: 'В действующей инструкции изменился срок хранения.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить решение' }));
    expect(await screen.findByRole('link', { name: 'Срок хранения' })).toHaveAttribute('href', '/courses/new-course/edit?lessonId=new-lesson');
    expect(api.post).toHaveBeenCalledTimes(1);

    view.unmount();
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть анализ версии' }));
    expect(await screen.findByRole('link', { name: 'Срок хранения' })).toHaveAttribute('href', '/courses/new-course/edit?lessonId=new-lesson');
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it('lets a methodologist choose another eligible owner and save without dates', async () => {
    render(<SourceActualityPanel userId="c88788a4-61c7-4c0a-9b89-e8d9b8ba22cd" catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    const select = await screen.findByRole('combobox', { name: 'Владелец источника' });
    fireEvent.change(select, { target: { value: ownerId } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/v1/admin/source-actuality/${family.source_family_id}/policy`,
      { owner_id: ownerId, reviewed_at: null, next_review_at: null },
    ));
  });

  it('does not offer the platform operator as a tenant owner during preview', async () => {
    const props = { userId: 'f625782b-c828-4917-b4e5-251836887316', isImpersonating: true, catalogDocuments: [] };
    render(<SourceActualityPanel {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    expect(screen.queryByRole('button', { name: 'Назначить мне' })).not.toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Владелец источника' })).toBeEnabled();
    expect(api.put).not.toHaveBeenCalled();
  });

  it('assigns an ordinary methodologist to themselves without requiring dates', async () => {
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Назначить мне' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Назначить мне' }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(expect.stringContaining('/policy'), {
      owner_id: ownerId, reviewed_at: null, next_review_at: null,
    }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('rejects an inverted review window before making a request and retains input', async () => {
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Проверен'), { target: { value: '2026-12-20T10:00' } });
    fireEvent.change(screen.getByLabelText('Следующая проверка'), { target: { value: '2026-12-19T10:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Следующая проверка не может быть раньше');
    expect(screen.getByLabelText('Проверен')).toHaveValue('2026-12-20T10:00');
    expect(api.put).not.toHaveBeenCalled();
  });

  it.each([
    { detail: 'Policy owner must be an active tenant methodologist' },
    { error: 'http_error', message: 'Policy owner must be an active tenant methodologist' },
  ])('keeps the selected owner and dates after a rejected save (%j)', async (data) => {
    vi.mocked(api.put).mockRejectedValue({ response: { status: 422, data } });
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    const select = await screen.findByRole('combobox', { name: 'Владелец источника' });
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.change(select, { target: { value: ownerId } });
    fireEvent.change(screen.getByLabelText('Следующая проверка'), { target: { value: '2026-12-20T10:00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('выберите действующего методиста компании');
    expect(select).toHaveValue(ownerId);
    expect(screen.getByLabelText('Следующая проверка')).toHaveValue('2026-12-20T10:00');
  });

  it('loads later pages and excludes ineligible candidates', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: !String(url).startsWith('/v1/users?')
      ? { items: [family] }
      : String(url).endsWith('page=1')
        ? { users: [{ id: 'inactive', role: 'methodologist', is_active: false }], total: 2 }
        : { users: [{ id: ownerId, first_name: 'Тестовый', last_name: 'методист', role: 'methodologist', is_active: true }], total: 2 }
    }) as never);
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    expect(await screen.findByRole('option', { name: 'Тестовый методист' })).toHaveValue(ownerId);
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(vi.mocked(api.get).mock.calls.some(([url]) => String(url).endsWith('page=2'))).toBe(true);
  });

  it('does not close another source dialog when an earlier save finishes', async () => {
    let finishSave!: (value: unknown) => void;
    vi.mocked(api.put).mockImplementation(() => new Promise((resolve) => { finishSave = resolve; }) as never);
    vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).startsWith('/v1/users?')
      ? { users: [{ id: ownerId, first_name: 'Тестовый', last_name: 'методист', role: 'methodologist', is_active: true }], total: 1 }
      : { items: [family, { ...family, source_family_id: 'second-family', title: 'Second synthetic source' }] }
    }) as never);
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click((await screen.findAllByRole('button', { name: 'Управлять источником' }))[0]);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Закрыть' })[1]);
    fireEvent.click(screen.getAllByRole('button', { name: 'Управлять источником' })[1]);
    await act(async () => { finishSave({ data: {} }); });
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveAccessibleName('Second synthetic source'));
  });

  it('does not mislabel schema validation errors as an invalid owner', async () => {
    vi.mocked(api.put).mockRejectedValue({ response: { status: 422, data: { detail: [{ type: 'value_error' }] } } });
    render(<SourceActualityPanel userId={ownerId} catalogDocuments={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Управлять источником' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Проверьте владельца, даты и время');
  });
});
