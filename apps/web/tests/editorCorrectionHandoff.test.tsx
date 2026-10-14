import { createRef, StrictMode, useRef, useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const wire = vi.hoisted(() => ({ create: vi.fn(), load: vi.fn(), apply: vi.fn(), receipt: vi.fn(), file: vi.fn() }));
let lang = 'ru';
let session = { accessToken: 'test-token', user: { role: 'methodologist', user_id: 'actor-1', tenant_id: 'tenant-1', impersonated_by: undefined as string | undefined } };
const translate = (key: string) => ({ 'aiAssistant.chatPlaceholder': 'Ask AI', 'aiGeneration.chat.send': 'Send', 'aiAssistant.applyLesson': 'Legacy Apply' }[key] ?? key);
vi.mock('@/store/authStore', () => ({ useAuthStore: (selector: (s: typeof session) => unknown) => selector(session) }));
vi.mock('@/store/languageStore', () => ({ useLanguageStore: (selector: (s: { lang: string }) => unknown) => selector({ lang }) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang, t: translate }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('@/lib/lessonCorrection', async (original) => ({ ...await original<object>(), createLessonCorrection: wire.create, loadLessonCorrection: wire.load, applyLessonCorrection: wire.apply, loadLessonCorrectionApplication: wire.receipt, loadCorrectionSourceFile: wire.file }));
vi.mock('next/navigation', () => ({ useParams: () => ({ id: courseId }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/components/course-approval/ApprovalPolicyCard', () => ({ ApprovalPolicyCard: () => null }));
vi.mock('@/components/ui/ConfirmDialog', () => ({ useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(false), dialog: null }) }));
import { buildCorrectionHandoffInstruction } from '@/lib/lessonCorrection';
import { AIChatPanel } from '@/components/ai/AIChatPanel';
import LessonCorrectionPanel, { type LessonCorrectionPanelHandle } from '@/features/methodologist-workbench/LessonCorrectionPanel';
import CourseEditPage from '@/app/courses/[id]/edit/page';
import actualFollowup from './fixtures/editor-followup-dev50.json';
const lessonId = '00000000-0000-4000-8000-000000000002';
const courseId = '00000000-0000-4000-8000-000000000003';
const planId = '00000000-0000-4000-8000-000000000001';
const props = { courseId, lessonId, lessonTitle: 'Урок', savedContent: 'Сохранённый текст', dirty: false, editorBusy: false, onApplied: vi.fn(), onApplyingChange: vi.fn(), onReload: vi.fn() };
const preview = { plan_id: planId, lesson_id: lessonId, revision: 3, fingerprint: 'a'.repeat(64), state: 'ready', expires_at: '2030-01-01T00:00:00Z', before_content: props.savedContent, proposal: { content: 'Проверенный по источнику вариант', citations: [], provenance: { provider: 'fake.test', model_id: 'fake', prompt_version: 'v1', generator_version: 'v1' }, quality_policy: 'lesson-quality-v1' } };
const receipt = { plan_id: planId, lesson_id: lessonId, course_id: courseId, revision: 3, fingerprint: preview.fingerprint, before_sha256: 'b'.repeat(64), after_sha256: 'c'.repeat(64), applied_at: '2026-10-14T08:00:00Z', state: 'applied', source_review: 'needs_review', quiz_review: 'needs_review' };
function defer<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function stage(ref: ReturnType<typeof createRef<LessonCorrectionPanelHandle>>, instruction = 'Проверь вариант') {
  let accepted = false;
  act(() => { accepted = ref.current?.stageInstruction({ lessonId, locale: lang as 'ru', instruction }) ?? false; });
  return accepted;
}
async function prepare() { fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Объясни проще' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' })); await screen.findByText('Предложенный вариант'); }

describe('editor correction handoff V1', () => {
  beforeEach(() => {
    vi.clearAllMocks(); lang = 'ru'; session = { accessToken: 'test-token', user: { role: 'methodologist', user_id: 'actor-1', tenant_id: 'tenant-1', impersonated_by: undefined } };
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true'); vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED', 'true');
    window.history.replaceState({}, '', '/courses/qa/edit?other=keep');
    wire.create.mockResolvedValue(preview); wire.load.mockResolvedValue(preview); wire.apply.mockResolvedValue(receipt); wire.receipt.mockResolvedValue(null);
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it('replays the real DEV plain-text simplification and stages that reply, not the earlier card', async () => {
    const handoff = vi.fn().mockReturnValue(true); const onClose = vi.fn();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...actualFollowup.first, apply_lesson_id: lessonId }) })
      .mockResolvedValueOnce({ ok: true, json: async () => actualFollowup.followup });
    vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={onClose} courseId={courseId} focusLessonId={lessonId} onReviewLessonSuggestion={handoff} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Предложи вариант' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText(actualFollowup.first.reply);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Сделай этот вариант проще' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText((_, element) => element?.children.length === 0 && element.textContent === actualFollowup.followup.reply);
    fireEvent.click(screen.getByRole('button', { name: 'Проверить этот ответ по источникам' }));
    expect(handoff).toHaveBeenCalledWith(lessonId, buildCorrectionHandoffInstruction('Сделай этот вариант проще', actualFollowup.followup.reply, 'ru'));
    expect(onClose).toHaveBeenCalledTimes(1); expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.every(([, request]) => request.method === 'POST')).toBe(true);
  });

  it.each(['refusal', 'unknown-eligibility', 'initial-advice', 'wrong-prior-target', 'audience', 'no-owner', 'course', 'module', 'partial-id', 'partial-title', 'empty-content', 'empty-id'] as const)('does not admit a plain reply for %s', async boundary => {
    const handoff = vi.fn();
    const first = boundary === 'initial-advice' ? { reply: actualFollowup.first.reply, history_eligible: true }
      : { ...actualFollowup.first, apply_lesson_id: boundary === 'wrong-prior-target' ? planId : lessonId };
    const second = { ...actualFollowup.followup, history_eligible: boundary === 'refusal' ? false : boundary === 'unknown-eligibility' ? undefined : true,
      apply_lesson_id: boundary === 'partial-id' ? planId : boundary === 'empty-id' ? '' : null,
      apply_lesson_title_hint: boundary === 'partial-title' ? 'Unmatched metadata' : null,
      apply_lesson_content: boundary === 'empty-content' ? '' : null,
      audience_recommendation: boundary === 'audience' ? { course_status: 'draft', recommended_scopes: [], matched_employee_count: 0, already_enrolled_count: 0, data_warnings: [] } : null };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => first }).mockResolvedValueOnce({ ok: true, json: async () => second }); vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={vi.fn()} courseId={courseId} focusLessonId={boundary === 'course' || boundary === 'module' ? undefined : lessonId} focusModuleId={boundary === 'module' ? 'module-1' : undefined} onReviewLessonSuggestion={boundary === 'no-owner' ? undefined : handoff} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Предложи вариант' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' })); await screen.findByText(first.reply);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Сделай этот вариант проще' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText((_, element) => element?.children.length === 0 && element.textContent === second.reply);
    expect(screen.queryByRole('button', { name: 'Проверить этот ответ по источникам' })).toBeNull(); expect(handoff).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(2); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
  });

  it.each(['ru', 'kk', 'en'] as const)('localizes the explicit plain-reply review action in %s', async locale => {
    lang = locale; const handoff = vi.fn().mockReturnValue(true);
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...actualFollowup.first, apply_lesson_id: lessonId }) }).mockResolvedValueOnce({ ok: true, json: async () => actualFollowup.followup }); vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={vi.fn()} courseId={courseId} focusLessonId={lessonId} onReviewLessonSuggestion={handoff} />);
    for (const message of ['Предложи вариант', 'Сделай проще']) {
      fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: message } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
      await screen.findByText((_, element) => element?.children.length === 0 && element.textContent === (message === 'Предложи вариант' ? actualFollowup.first.reply : actualFollowup.followup.reply));
    }
    fireEvent.click(screen.getByRole('button', { name: { ru: 'Проверить этот ответ по источникам', kk: 'Осы жауапты дереккөздермен тексеру', en: 'Review this reply against sources' }[locale] }));
    expect(handoff).toHaveBeenCalledWith(lessonId, buildCorrectionHandoffInstruction('Сделай проще', actualFollowup.followup.reply, locale)); expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(['oversize', 'refused-staging', 'pending'] as const)('never silently executes or replaces intent for a %s plain reply', async boundary => {
    const handoff = vi.fn().mockReturnValue(boundary !== 'refused-staging'); const onClose = vi.fn(); const pending = defer<{ ok: boolean; json: () => Promise<typeof actualFollowup.followup> }>();
    const second = { ...actualFollowup.followup, reply: boundary === 'oversize' ? 'a'.repeat(4000) : actualFollowup.followup.reply };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...actualFollowup.first, apply_lesson_id: lessonId }) }).mockResolvedValueOnce({ ok: true, json: async () => second }).mockReturnValueOnce(pending.promise); vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={onClose} courseId={courseId} focusLessonId={lessonId} onReviewLessonSuggestion={handoff} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Предложи вариант' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' })); await screen.findByText(actualFollowup.first.reply);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Сделай проще' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText((_, element) => element?.children.length === 0 && element.textContent === second.reply);
    if (boundary === 'pending') {
      fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Ещё уточнение' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
      expect(screen.getByRole('button', { name: 'Проверить этот ответ по источникам' })).toBeDisabled();
    }
    fireEvent.click(screen.getByRole('button', { name: 'Проверить этот ответ по источникам' }));
    expect(onClose).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(boundary === 'pending' ? 3 : 2); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
    if (boundary === 'refused-staging') expect(handoff).toHaveBeenCalledWith(lessonId, buildCorrectionHandoffInstruction('Сделай проще', second.reply, 'ru'));
    else expect(handoff).not.toHaveBeenCalled();
    if (boundary === 'pending') await act(async () => pending.resolve({ ok: true, json: async () => actualFollowup.followup }));
  });

  it.each(['ru', 'kk', 'en'] as const)('composes a bounded unverified candidate without truncation in %s', locale => {
    const value = buildCorrectionHandoffInstruction('Сделай этот вариант проще', 'Оба срока сохраняются. Нужен владелец.', locale);
    expect(value).toContain('Сделай этот вариант проще'); expect(value).toContain('Оба срока сохраняются. Нужен владелец.');
    expect(Array.from(value).length).toBeLessThanOrEqual(4000);
    expect(() => buildCorrectionHandoffInstruction('Уточни', 'a'.repeat(4000), locale)).toThrow();
    expect(() => buildCorrectionHandoffInstruction('', 'Вариант', locale)).toThrow();
  });
  it('stages instruction without generating or applying and clears old consent/locator', async () => {
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<StrictMode><LessonCorrectionPanel ref={ref} {...props} /></StrictMode>);
    await prepare(); fireEvent.click(screen.getByRole('checkbox', { name: 'Я проверил правку и источники' }));
    expect(stage(ref)).toBe(true);
    expect(screen.getByRole('textbox', { name: 'Что изменить в уроке' })).toHaveValue('Проверь вариант');
    expect(screen.queryByRole('button', { name: 'Применить правку к уроку' })).toBeNull();
    expect(new URL(window.location.href).searchParams.get('correction_plan')).toBeNull();
    expect(new URL(window.location.href).searchParams.get('other')).toBe('keep');
    expect(wire.create).toHaveBeenCalledTimes(1); expect(wire.apply).not.toHaveBeenCalled();
  });
  it.each(['dirty', 'editorBusy'] as const)('refuses %s staging without discarding the current instruction', field => {
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} {...{ [field]: true }} />);
    expect(stage(ref)).toBe(false); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
  });
  it('refuses wrong lesson, locale, oversize and unmounted stale handle', () => {
    const ref = createRef<LessonCorrectionPanelHandle>(); const view = render(<LessonCorrectionPanel ref={ref} {...props} />);
    const handle = ref.current!;
    expect(handle.stageInstruction({ lessonId: courseId, instruction: 'Проверь', locale: 'ru' })).toBe(false);
    expect(handle.stageInstruction({ lessonId, instruction: 'Проверь', locale: 'en' })).toBe(false);
    expect(stage(ref, 'a'.repeat(4001))).toBe(false);
    view.unmount(); expect(handle.stageInstruction({ lessonId, instruction: 'Проверь', locale: 'ru' })).toBe(false);
  });
  it('rejects a handle retained across a locale or actor change', () => {
    const ref = createRef<LessonCorrectionPanelHandle>(); const view = render(<LessonCorrectionPanel ref={ref} {...props} />);
    const oldLocale = ref.current!; lang = 'en'; view.rerender(<LessonCorrectionPanel ref={ref} {...props} />);
    expect(oldLocale.stageInstruction({ lessonId, instruction: 'Old context', locale: 'ru' })).toBe(false);
    const oldActor = ref.current!; session = { ...session, accessToken: 'new-token', user: { ...session.user, tenant_id: 'tenant-2' } };
    view.rerender(<LessonCorrectionPanel ref={ref} {...props} />);
    expect(oldActor.stageInstruction({ lessonId, instruction: 'Old context', locale: 'en' })).toBe(false);
    expect(stage(ref, 'Current context')).toBe(true);
  });
  it.each(['student', 'admin', 'impersonation', 'disabled'] as const)('does not expose a staging handle for %s', condition => {
    if (condition === 'disabled') vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED', 'false');
    else if (condition === 'impersonation') session.user.impersonated_by = 'actor-2';
    else session.user.role = condition;
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    expect(ref.current).toBeNull(); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
  });
  it('keeps the chat open and never PATCHes when local staging is refused or candidate is oversized', async () => {
    const callback = vi.fn(() => false); const close = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ reply: 'Предложение', apply_lesson_id: lessonId, apply_lesson_content: 'Короткий вариант' }) }); vi.stubGlobal('fetch', fetchMock);
    render(<AIChatPanel open onClose={close} courseId={courseId} focusLessonId={lessonId} onReviewLessonSuggestion={callback} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Уточни' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('Предложение'); fireEvent.click(screen.getByRole('button', { name: 'Проверить вариант по источникам' }));
    expect(callback).toHaveBeenCalledTimes(1); expect(close).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ reply: 'Большой вариант', apply_lesson_id: lessonId, apply_lesson_content: 'a'.repeat(4000) }) });
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Уточни ещё' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' })); await screen.findByText('Большой вариант');
    fireEvent.click(screen.getAllByRole('button', { name: 'Проверить вариант по источникам' })[1]);
    expect(callback).toHaveBeenCalledTimes(1); expect(close).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it('preserves unknown preview request and blocks staging until its same request is resolved', async () => {
    wire.create.mockRejectedValue(new Error('lost transport'));
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Ответ на запрос не получен/); expect(stage(ref)).toBe(false);
    expect(screen.getByRole('textbox', { name: 'Что изменить в уроке' })).toHaveValue('Первый запрос');
    const first = wire.create.mock.calls[0][0]; wire.create.mockResolvedValue(preview); fireEvent.click(screen.getByRole('button', { name: 'Проверить тот же запрос' }));
    await screen.findByText('Предложенный вариант'); expect(wire.create.mock.calls[1][0]).toEqual(first); expect(stage(ref)).toBe(true);
  });
  it('keeps a restored plan locator when receipt lookup is unavailable, including locale changes', async () => {
    window.history.replaceState({}, '', `/courses/qa/edit?correction_plan=${planId}`); wire.receipt.mockRejectedValue(new Error('offline'));
    const ref = createRef<LessonCorrectionPanelHandle>(); const view = render(<LessonCorrectionPanel ref={ref} {...props} />);
    await screen.findByRole('alert'); expect(stage(ref)).toBe(false);
    lang = 'en'; view.rerender(<LessonCorrectionPanel ref={ref} {...props} />);
    expect(stage(ref)).toBe(false); expect(new URL(window.location.href).searchParams.get('correction_plan')).toBe(planId);
    expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
  });
  it('does not allow instruction editing to discard an unknown create request', async () => {
    wire.create.mockRejectedValueOnce(new Error('lost transport'));
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    const input = screen.getByRole('textbox', { name: 'Что изменить в уроке' }); fireEvent.change(input, { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Ответ на запрос не получен/); const first = wire.create.mock.calls[0][0];
    expect(input).toBeDisabled(); fireEvent.change(input, { target: { value: 'Другой запрос' } });
    expect(input).toHaveValue('Первый запрос'); expect(stage(ref)).toBe(false);
    wire.create.mockResolvedValue(preview); fireEvent.click(screen.getByRole('button', { name: 'Проверить тот же запрос' })); await screen.findByText('Предложенный вариант');
    expect(wire.create.mock.calls[1][0]).toEqual(first); expect(input).toBeEnabled();
  });
  it('allows editing after a known structured refusal', async () => {
    wire.create.mockRejectedValueOnce({ response: { status: 400, data: { detail: 'instruction_unclear' } } });
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    const input = screen.getByRole('textbox', { name: 'Что изменить в уроке' }); fireEvent.change(input, { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Запрос отклонён/); expect(input).toBeEnabled(); expect(stage(ref)).toBe(true);
  });
  it('recovers an offline restore through the same plan reads without creating a new preview', async () => {
    window.history.replaceState({}, '', `/courses/qa/edit?correction_plan=${planId}`); wire.receipt.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(null);
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    await screen.findByRole('alert'); expect(screen.getByRole('textbox', { name: 'Что изменить в уроке' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку правки' })); await screen.findByText('Предложенный вариант');
    expect(wire.receipt).toHaveBeenCalledTimes(2); expect(wire.receipt.mock.calls.every(([id]) => id === planId)).toBe(true);
    expect(wire.load).toHaveBeenCalledWith(planId, expect.any(AbortSignal)); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled(); expect(stage(ref)).toBe(true);
  });
  it.each(['locale', 'savedContent'] as const)('preserves an abort-resistant create across %s change until its same outcome is known', async change => {
    const deferred = defer<typeof preview>(); wire.create.mockReturnValue(deferred.promise);
    const ref = createRef<LessonCorrectionPanelHandle>(); const view = render(<LessonCorrectionPanel ref={ref} {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    const request = wire.create.mock.calls[0][0]; const signal = wire.create.mock.calls[0][1];
    if (change === 'locale') lang = 'en';
    view.rerender(<LessonCorrectionPanel ref={ref} {...props} savedContent={change === 'savedContent' ? 'Обновлённый сохранённый текст' : props.savedContent} />);
    expect(stage(ref)).toBe(false); expect(signal.aborted).toBe(false); expect(wire.create).toHaveBeenCalledTimes(1);
    await act(async () => deferred.resolve(preview));
    expect(new URL(window.location.href).searchParams.get('correction_plan')).toBe(planId);
    expect(screen.getByRole('button', { name: change === 'locale' ? 'Apply correction to lesson' : 'Применить правку к уроку' })).toBeDisabled();
    expect(wire.create.mock.calls[0][0]).toEqual(request);
    expect(stage(ref)).toBe(true); expect(wire.create).toHaveBeenCalledTimes(1); expect(wire.apply).not.toHaveBeenCalled();
  });
  it('does not replace a server-pending plan even when transport has completed', async () => {
    wire.create.mockResolvedValue({ ...preview, state: 'pending', proposal: null, before_content: null, fingerprint: null });
    const ref = createRef<LessonCorrectionPanelHandle>(); const view = render(<LessonCorrectionPanel ref={ref} {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    await screen.findByText(/Предложение ещё готовится/); expect(stage(ref)).toBe(false);
    lang = 'en'; view.rerender(<LessonCorrectionPanel ref={ref} {...props} />); expect(stage(ref)).toBe(false);
    expect(new URL(window.location.href).searchParams.get('correction_plan')).toBe(planId);
    fireEvent.click(screen.getByRole('button', { name: 'Check preview' })); await screen.findByText('Proposed version');
    expect(stage(ref)).toBe(true); expect(wire.create).toHaveBeenCalledTimes(1);
  });
  it('blocks a pending preview and an unknown application without losing the seal', async () => {
    const pending = defer<typeof preview>(); wire.create.mockReturnValue(pending.promise);
    const ref = createRef<LessonCorrectionPanelHandle>(); render(<LessonCorrectionPanel ref={ref} {...props} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в уроке' }), { target: { value: 'Первый запрос' } }); fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' }));
    expect(stage(ref)).toBe(false); await act(async () => pending.resolve(preview));
    wire.apply.mockRejectedValue(new Error('lost transport')); fireEvent.click(screen.getByRole('checkbox', { name: 'Я проверил правку и источники' })); fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    await screen.findByRole('button', { name: 'Проверить результат' }); expect(stage(ref)).toBe(false);
    expect(new URL(window.location.href).searchParams.get('correction_plan')).toBe(planId);
    expect(wire.apply).toHaveBeenCalledWith({ plan_id: planId, revision: 3, fingerprint: preview.fingerprint }, expect.any(AbortSignal));
  });
  it('connects actual chat and actual correction owner, then applies only its reviewed seal', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ reply: 'Есть вариант', apply_lesson_id: lessonId, apply_lesson_content: 'Черновой вариант из чата' }) }); vi.stubGlobal('fetch', fetchMock);
    function Journey() {
      const ref = useRef<LessonCorrectionPanelHandle>(null); const [open, setOpen] = useState(true);
      return <><LessonCorrectionPanel ref={ref} {...props} /><AIChatPanel open={open} onClose={() => setOpen(false)} courseId={courseId} focusLessonId={lessonId} onReviewLessonSuggestion={(id, instruction) => ref.current?.stageInstruction({ lessonId: id, instruction, locale: 'ru' }) ?? false} /></>;
    }
    render(<Journey />); fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Упрости урок' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('Есть вариант'); fireEvent.click(screen.getByRole('button', { name: 'Проверить вариант по источникам' }));
    expect(screen.queryByRole('dialog')).toBeNull(); expect(fetchMock).toHaveBeenCalledTimes(1); expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
    expect((screen.getByRole('textbox', { name: 'Что изменить в уроке' }) as HTMLTextAreaElement).value).toContain('Черновой вариант из чата');
    fireEvent.click(screen.getByRole('button', { name: 'Предложить правку' })); await screen.findByText('Предложенный вариант');
    expect(screen.getByRole('button', { name: 'Применить правку к уроку' })).toBeDisabled(); fireEvent.click(screen.getByRole('checkbox', { name: 'Я проверил правку и источники' })); fireEvent.click(screen.getByRole('button', { name: 'Применить правку к уроку' }));
    await screen.findByText('Правка применена'); expect(wire.apply).toHaveBeenCalledWith({ plan_id: planId, revision: 3, fingerprint: preview.fingerprint }, expect.any(AbortSignal)); expect(fetchMock.mock.calls.every(([, opts]) => opts.method !== 'PATCH')).toBe(true);
  });
  it.each(['ready', 'dirty', 'published', 'nontext', 'disabled'] as const)('assembles the actual course-editor consumer with %s context', async context => {
    if (context === 'disabled') vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED', 'false');
    const contentType = context === 'nontext' ? 'pdf' : 'text';
    const fetchMock = vi.fn(async (input: unknown) => {
      const url = String(input);
      const body = url.endsWith('/ai/chat') ? { reply: 'Вариант редактора', apply_lesson_id: lessonId, apply_lesson_content: 'Черновой вариант' }
        : url.endsWith('/structure') ? { modules: [{ id: 'module-1', title: 'Модуль', lessons: [{ id: lessonId, title: 'Синтетический урок', content_type: contentType }] }] }
        : url.includes('/lessons/') ? { id: lessonId, title: 'Синтетический урок', content: props.savedContent, content_type: contentType }
        : { id: courseId, title: 'Синтетический курс', status: context === 'published' ? 'published' : 'draft', ai_generated: false, review_status: 'pending' };
      return { ok: true, json: async () => body };
    }); vi.stubGlobal('fetch', fetchMock);
    render(<CourseEditPage />); fireEvent.click(await screen.findByRole('button', { name: 'Синтетический урок' }));
    const lessonContent = await screen.findByRole('textbox', { name: 'authenticatedUi.editor.lessonContent' });
    if (context === 'dirty') fireEvent.change(lessonContent, { target: { value: 'Ручная несохранённая правка' } });
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.editor.lessonAssistantTitle' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask AI' }), { target: { value: 'Упрости' } }); fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('Вариант редактора'); fireEvent.click(screen.getByRole('button', { name: 'Проверить вариант по источникам' }));
    expect(wire.create).not.toHaveBeenCalled(); expect(wire.apply).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls.some((call: unknown[]) => (call[1] as RequestInit | undefined)?.method === 'PATCH')).toBe(false);
    if (context === 'ready') {
      expect(screen.queryByRole('dialog')).toBeNull();
      expect((screen.getByRole('textbox', { name: 'Что изменить в уроке' }) as HTMLTextAreaElement).value).toContain('Черновой вариант');
    } else expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
