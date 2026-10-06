import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const wire = vi.hoisted(() => ({ create: vi.fn(), load: vi.fn(), apply: vi.fn(), receipt: vi.fn() }));
let lang = 'ru';
let session = { accessToken: 'token-1', user: { role: 'methodologist', user_id: 'actor-1', impersonated_by: undefined as string | undefined } };
vi.mock('@/lib/lessonCorrection', () => ({ createLessonCorrection: wire.create, loadLessonCorrection: wire.load, applyLessonCorrection: wire.apply, loadLessonCorrectionApplication: wire.receipt }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (s: typeof session) => unknown) => selector(session) }));
vi.mock('@/store/languageStore', () => ({ useLanguageStore: (selector: (s: { lang: string }) => unknown) => selector({ lang }) }));
import LessonCorrectionPanel from '@/features/methodologist-workbench/LessonCorrectionPanel';

const planId = '00000000-0000-4000-8000-000000000001';
const lessonId = '00000000-0000-4000-8000-000000000002';
const courseId = '00000000-0000-4000-8000-000000000003';
const preview = {
  plan_id: planId, revision: 7, lesson_id: lessonId, state: 'ready', expires_at: '2030-01-01T00:00:00Z',
  fingerprint: 'a'.repeat(64), before_content: 'Сохранённый урок',
  proposal: { content: '<script>plain text only</script>\nПредложенный урок', citations: [{ document_id: courseId, locator: 'fact:guides', evidence_hash: 'b'.repeat(64) }], provenance: { provider: 'fake.test', model_id: 'fake-v1', prompt_version: 'v1', generator_version: 'v1' }, quality_policy: 'lesson-quality-v1' },
};
const receipt = { plan_id: planId, lesson_id: lessonId, course_id: courseId, revision: 7, fingerprint: preview.fingerprint, before_sha256: 'b'.repeat(64), after_sha256: 'c'.repeat(64), applied_at: '2026-10-05T12:00:00Z', state: 'applied', source_review: 'needs_review', quiz_review: 'needs_review' };
const props = { courseId, lessonId, lessonTitle: 'Урок 1', savedContent: preview.before_content, dirty: false, editorBusy: false, onApplied: vi.fn(), onApplyingChange: vi.fn(), onReload: vi.fn() };
const prepare = async () => {
  fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Уточни объяснение по исходному документу' } });
  fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
  await screen.findByText('Предложенный вариант');
};
const consent = () => fireEvent.click(screen.getByRole('checkbox', { name: 'Я проверил правку и источники' }));

describe('LessonCorrectionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true');
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED', 'true');
    lang = 'ru'; session = { accessToken: 'token-1', user: { role: 'methodologist', user_id: 'actor-1', impersonated_by: undefined } };
    window.history.replaceState({}, '', '/courses/course/edit?other=keep#editor');
    wire.create.mockResolvedValue(preview); wire.load.mockResolvedValue(preview); wire.receipt.mockResolvedValue(null); wire.apply.mockResolvedValue(receipt);
  });
  afterEach(() => vi.unstubAllEnvs());

  it('shows server before/after as text and applies only the reviewed server seal', async () => {
    render(<LessonCorrectionPanel {...props} />); await prepare();
    expect(screen.getByText(preview.before_content)).toBeInTheDocument();
    expect(screen.getByText(/plain text only/).querySelector('script')).toBeNull();
    const apply = screen.getByRole('button', { name: 'Применить правку к уроку' });
    expect(apply).toBeDisabled(); expect(wire.apply).not.toHaveBeenCalled();
    consent(); fireEvent.click(apply);
    await screen.findByText('Правка применена');
    expect(wire.apply).toHaveBeenCalledWith({ plan_id: planId, revision: 7, fingerprint: preview.fingerprint }, expect.any(AbortSignal));
    expect(props.onApplied).toHaveBeenCalledWith(receipt, preview.proposal.content, preview.before_content);
    expect(new URL(window.location.href).searchParams.get('other')).toBe('keep');
    expect(window.location.hash).toBe('#editor');
  });

  it('invalidates confirmation after an instruction edit or unsaved manual change', async () => {
    const view = render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    view.rerender(<LessonCorrectionPanel {...props} dirty />);
    expect(screen.getByRole('button', { name: 'Применить правку к уроку' })).toBeDisabled();
    expect(screen.getByText(/Сначала сохраните или отмените ручные изменения/)).toBeInTheDocument();
    view.rerender(<LessonCorrectionPanel {...props} />);
    expect(screen.queryByRole('button', { name: 'Применить правку к уроку' })).not.toBeInTheDocument();
    await prepare(); consent();
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Новая инструкция' } });
    expect(screen.queryByText('Предложенный вариант')).not.toBeInTheDocument(); expect(wire.apply).not.toHaveBeenCalled();
  });

  it.each(['busy', 'lost-response'])('checks receipt first after %s without a second POST', async (failure) => {
    wire.apply.mockRejectedValue(failure === 'busy' ? { response: { status: 409, data: { detail: 'correction_application_busy' } } } : new Error('network'));
    wire.receipt.mockResolvedValue(receipt);
    render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    await screen.findByText('Правка применена');
    expect(wire.receipt).toHaveBeenCalledWith(planId, expect.any(AbortSignal)); expect(wire.apply).toHaveBeenCalledTimes(1);
  });

  it('shows an actionable refusal and releases the instruction after a structured preview 409', async () => {
    wire.create.mockRejectedValueOnce({ response: { status: 409, data: { error: 'conflict', message: 'lesson_source_provenance_unavailable' } } });
    render(<LessonCorrectionPanel {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Уточни объяснение по исходному документу' } });
    fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Проверьте источники и уточните поручение/);
    expect(screen.queryByRole('button', { name: 'Проверить тот же запрос' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Предложить правку' })).toBeEnabled();
    expect(wire.create).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['network loss', new Error('lost')],
    ['structured HTTP 503', { response: { status: 503, data: { error: 'temporary_failure', message: 'retry later' } } }],
    ['unstructured HTTP 409', { response: { status: 409, data: 'conflict' } }],
  ])('retains the same request for explicit retry after %s', async (_label, failure) => {
    wire.create.mockRejectedValueOnce(failure).mockResolvedValueOnce(preview);
    render(<LessonCorrectionPanel {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Уточни объяснение по исходному документу' } });
    fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Ответ на запрос не получен/);
    const request = wire.create.mock.calls[0][0];
    expect(screen.getByRole('button', { name: 'Проверить тот же запрос' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Проверить тот же запрос' }));
    await screen.findByText('Предложенный вариант');
    expect(wire.create).toHaveBeenCalledTimes(2);
    expect(wire.create.mock.calls[1][0]).toEqual(request);
  });

  it.each([
    ['ru', 'Запрос отклонён. Проверьте источники и уточните поручение'],
    ['kk', 'Сұрау қабылданбады. Дереккөздерді тексеріп, тапсырманы нақтылап'],
    ['en', 'The request was refused. Check the sources and clarify the instruction'],
  ])('localizes an authoritative preview 409 refusal for %s', async (locale, message) => {
    lang = locale;
    wire.create.mockRejectedValueOnce({ response: { status: 409, data: { error: 'conflict', message: 'lesson_source_provenance_unavailable' } } });
    render(<LessonCorrectionPanel {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Clarify the source-backed explanation' } });
    fireEvent.click(screen.getByRole('button', { name: /Предложить правку|Түзету ұсыну|Propose correction/ }));
    await screen.findByText(new RegExp(message));
    expect(screen.queryByRole('button', { name: /Проверить тот же запрос|Сол сұрауды тексеру|Check the same request/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Предложить правку|Түзету ұсыну|Propose correction/ })).toBeEnabled();
    expect(wire.create).toHaveBeenCalledTimes(1);
  });

  it('does not interpret missing or unavailable receipt as success; retry is explicit', async () => {
    wire.apply.mockRejectedValueOnce(new Error('lost'));
    render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    await screen.findByText(/Результат пока не подтверждён/);
    expect(props.onApplied).not.toHaveBeenCalled(); expect(wire.apply).toHaveBeenCalledTimes(1);
    wire.receipt.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Проверить результат' }));
    await screen.findByText(/Результат пока не подтверждён/);
    expect(wire.apply).toHaveBeenCalledTimes(1);
    wire.receipt.mockResolvedValue(null);
    fireEvent.click(screen.getByRole('button', { name: 'Повторить это подтверждение' }));
    await screen.findByText('Правка применена'); expect(wire.apply).toHaveBeenCalledTimes(2);
  });

  it('restores historical receipt before preview, without overwriting current editor', async () => {
    window.history.replaceState({}, '', `/courses/course/edit?correction_plan=${planId}`);
    wire.receipt.mockResolvedValue(receipt);
    render(<StrictMode><LessonCorrectionPanel {...props} savedContent="Поздняя ручная версия" /></StrictMode>);
    await screen.findByText('Правка применена');
    expect(wire.load).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled(); expect(props.onApplied).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Обновить сохранённый урок' })); expect(props.onReload).toHaveBeenCalledOnce();
  });

  it('allows explicit re-review of the same uncertain seal after manual changes are discarded', async () => {
    wire.apply.mockRejectedValueOnce(new Error('lost'));
    const view = render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    await screen.findByText(/Результат пока не подтверждён/);
    view.rerender(<LessonCorrectionPanel {...props} dirty />);
    view.rerender(<LessonCorrectionPanel {...props} />);
    const reviewed = screen.getByRole('checkbox', { name: 'Я проверил правку и источники' });
    expect(reviewed).not.toBeChecked(); expect(reviewed).toBeEnabled(); fireEvent.click(reviewed);
    fireEvent.click(screen.getByRole('button', { name: 'Повторить это подтверждение' }));
    await screen.findByText('Правка применена');
    expect(wire.apply.mock.calls[1][0]).toEqual({ plan_id: planId, revision: 7, fingerprint: preview.fingerprint });
  });

  it('shows factual pending state with GET refresh, not another model request', async () => {
    wire.create.mockResolvedValue({ ...preview, state: 'pending', proposal: null, fingerprint: null, before_content: null });
    render(<LessonCorrectionPanel {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Уточни урок' } });
    fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Предложение ещё готовится/);
    fireEvent.click(screen.getByRole('button', { name: 'Проверить предпросмотр' })); await screen.findByText('Предложенный вариант');
    expect(wire.load).toHaveBeenCalledWith(planId, expect.any(AbortSignal)); expect(wire.create).toHaveBeenCalledTimes(1);
  });

  it('suppresses an application response after selected lesson or session changes', async () => {
    let resolve!: (value: unknown) => void; wire.apply.mockReturnValue(new Promise((r) => { resolve = r; }));
    const view = render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    session = { ...session, accessToken: 'token-2' };
    view.rerender(<LessonCorrectionPanel {...props} lessonId={courseId} />);
    await act(async () => { resolve(receipt); });
    expect(props.onApplied).not.toHaveBeenCalled();
  });

  it('rejects a restored plan for a different lesson', async () => {
    window.history.replaceState({}, '', `/courses/course/edit?correction_plan=${planId}`);
    wire.receipt.mockResolvedValue({ ...receipt, lesson_id: courseId });
    render(<LessonCorrectionPanel {...props} />); await screen.findByRole('alert');
    expect(screen.queryByText('Правка применена')).not.toBeInTheDocument(); expect(wire.load).not.toHaveBeenCalled();
  });

  it('expires the button and clears unapplied preview when locale changes', async () => {
    wire.create.mockResolvedValue({ ...preview, expires_at: '2000-01-01T00:00:00Z' });
    const view = render(<LessonCorrectionPanel {...props} />); await prepare(); consent();
    expect(screen.getByRole('button', { name: 'Применить правку к уроку' })).toBeDisabled();
    lang = 'kk'; view.rerender(<LessonCorrectionPanel {...props} />);
    expect(screen.queryByText('Предложенный вариант')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'AI көмегімен сабақты түзету' })).toBeInTheDocument(); expect(wire.apply).not.toHaveBeenCalled();
  });

  it.each(['flag', 'role', 'impersonation'])('hides entry for %s denial', (reason) => {
    if (reason === 'flag') vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED', 'false');
    if (reason === 'role') session.user.role = 'administrator';
    if (reason === 'impersonation') session.user.impersonated_by = 'platform-actor';
    render(<LessonCorrectionPanel {...props} />); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
});
