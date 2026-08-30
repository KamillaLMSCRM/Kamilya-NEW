import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const postMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { post: postMock } }));
import { QuestionAssistantPreview } from '@/components/quizzes/QuestionAssistantPreview';
import { EditorAssistantPreviewResponse } from '@/lib/editorAssistant';

const previewIds = { quiz: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', question: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' };

const completedPreview: EditorAssistantPreviewResponse = {
  request_id: '11111111-1111-4111-8111-111111111111', preview_id: '22222222-2222-4222-8222-222222222222', state: 'completed', applicability: 'applicable_with_warnings', base_snapshot_token: 'a'.repeat(64),
  operations: [{ operation: 'replace', field_path: 'question.answer_options', before_value: [{ choice_id: '11111111-1111-1111-1111-111111111111', text: 'Короткий ответ', is_correct: true }, { choice_id: '22222222-2222-2222-2222-222222222222', text: 'Нет', is_correct: false }], after_value: [{ choice_id: '11111111-1111-1111-1111-111111111111', text: 'Короткий ответ', is_correct: true }, { choice_id: '22222222-2222-2222-2222-222222222222', text: 'Подробный, но неверный вариант ответа', is_correct: false }] }],
  validation: { status: 'warn', issues: [{ code: 'invalid_operation', message: 'Предложение содержит недопустимое изменение.', blocking: false, field_path: 'question.answer_options' }] }, source: { source_reference_count: 1, references: [{ source_id: 'source-1', document_title: 'Регламент', locator: 'с. 4' }] }, provenance: { prompt_version: 'v1', generator_version: 'v1', validator_version: 'v1' }, failure: null,
};
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((result) => { resolve = result; }); return { promise, resolve }; }

describe('QuestionAssistantPreview', () => {
  beforeEach(() => { vi.restoreAllMocks(); postMock.mockReset(); postMock.mockResolvedValue({ data: completedPreview }); vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValueOnce('11111111-1111-4111-8111-111111111111').mockReturnValueOnce('22222222-2222-4222-8222-222222222222').mockReturnValueOnce('33333333-3333-4333-8333-333333333333').mockReturnValueOnce('44444444-4444-4444-8444-444444444444'); });
  it('blocks a dirty form with actionable save-first guidance', () => {
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} isDirty disabledReason="Сначала сохраните изменения вопроса, пояснения или вариантов ответа, затем сформируйте предложение." />);
    expect(screen.getByRole('button', { name: 'Сформировать предложение помощника' })).toBeDisabled();
    expect(screen.getByText('Сначала сохраните изменения вопроса, пояснения или вариантов ответа, затем сформируйте предложение.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Инструкция помощнику' })).toBeDisabled();
  });
  it('uses explicit intent chips, preserves the single correct marker, and never renders IDs', async () => {
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.click(screen.getByRole('button', { name: 'Добавить контекст' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Добавь контекст' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    await screen.findByText('Предложение готово. Ничего не применено к вопросу.');
    expect(postMock.mock.calls[0][1]).toMatchObject({ intent: 'add_context', instruction: 'Добавь контекст' });
    expect(screen.getAllByText('Правильный ответ')).toHaveLength(2);
    expect(screen.queryByText('11111111-1111-1111-1111-111111111111')).not.toBeInTheDocument();
  });
  it('ignores a stale completion after instruction changes and submits the new request with rotated keys', async () => {
    const first = deferred<{ data: EditorAssistantPreviewResponse }>();
    postMock.mockReturnValueOnce(first.promise).mockResolvedValueOnce({ data: completedPreview });
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    const input = screen.getByRole('textbox', { name: 'Инструкция помощнику' }); const submit = screen.getByRole('button', { name: 'Сформировать предложение помощника' });
    fireEvent.change(input, { target: { value: 'Первая инструкция' } }); fireEvent.click(submit);
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: 'Вторая инструкция' } });
    first.resolve({ data: completedPreview });
    await waitFor(() => expect(submit).not.toBeDisabled());
    fireEvent.click(submit);
    await screen.findByText('Предложение готово. Ничего не применено к вопросу.');
    expect(postMock).toHaveBeenCalledTimes(2);
    expect(postMock.mock.calls[1][1]).toMatchObject({ request_key: '33333333-3333-4333-8333-333333333333', preview_key: '44444444-4444-4444-8444-444444444444', instruction: 'Вторая инструкция' });
  });
  it.each([
    ['requires_new_draft_revision', 'Сначала сохраните новую редакцию вопроса'],
    ['not_applicable', 'Помощник не может применить выбранную задачу'],
    ['stale', 'Вопрос изменился. Обновите сохранённую версию'],
  ] as const)('shows actionable applicability copy for %s', async (applicability, message) => {
    const failure = applicability === 'stale'
      ? { error_code: 'stale_base_version', message: 'Вопрос был изменён. Обновите данные и повторите запрос.' }
      : applicability === 'requires_new_draft_revision'
        ? { error_code: 'requires_new_draft_revision', message: 'Для опубликованного курса требуется новая черновая версия.' }
        : { error_code: 'internal_error', message: 'Не удалось подготовить предложение.' };
    postMock.mockResolvedValue({ data: { ...completedPreview, state: 'failed', applicability, operations: [], validation: null, source: { source_reference_count: 0, references: [] }, provenance: null, failure } });
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Улучши вопрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    expect(await screen.findByText(message, { exact: false })).toBeInTheDocument();
  });
  it.each([[401, 'Сессия истекла'], [404, 'Вопрос или его исходные материалы'], [409, 'Вопрос изменился или запрос конфликтует'], [422, 'Помощник не может подготовить предложение'], [500, 'Не удалось подготовить предложение']])('shows actionable safe HTTP %s copy once', async (status, message) => {
    postMock.mockRejectedValue(Object.assign(new Error('HTTP error'), { isAxiosError: true, response: { status, data: { detail: 'Bounded backend detail.' } } }));
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Улучши вопрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message); expect(postMock).toHaveBeenCalledTimes(1);
  });
  it('renders pending, failed, and malformed transport responses through the real parser without applying a change', async () => {
    const pending: EditorAssistantPreviewResponse = { ...completedPreview, state: 'pending', applicability: 'not_applicable', operations: [], validation: null, source: { source_reference_count: 0, references: [] }, provenance: null, failure: null };
    postMock.mockResolvedValueOnce({ data: pending });
    const { unmount } = render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Проверьте вопрос' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    expect(await screen.findByText('Предложение принято в обработку. Ничего не применено.')).toBeInTheDocument();
    unmount();

    const failed: EditorAssistantPreviewResponse = { ...pending, state: 'failed', applicability: 'stale', failure: { error_code: 'stale_base_version', message: 'Вопрос был изменён. Обновите данные и повторите запрос.' } };
    postMock.mockResolvedValueOnce({ data: failed });
    const failedView = render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Проверьте вопрос' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Помощник не смог подготовить безопасное предложение.');
    failedView.unmount();

    postMock.mockResolvedValueOnce({ data: { ...completedPreview, apply: { persisted: true } } });
    render(<QuestionAssistantPreview quizId={previewIds.quiz} questionId={previewIds.question} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Инструкция помощнику' }), { target: { value: 'Проверьте вопрос' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сформировать предложение помощника' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Помощник вернул некорректное предложение.');
    expect(screen.queryByText('Предложение готово. Ничего не применено к вопросу.')).not.toBeInTheDocument();
  });
});
