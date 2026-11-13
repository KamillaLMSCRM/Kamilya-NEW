import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn() },
  fetch: vi.fn(),
  confirm: vi.fn().mockResolvedValue(true),
  auth: { accessToken: 'synthetic', sessionEpoch: 0, user: { role: 'methodologist', user_id: 'actor', tenant_id: 'tenant' } },
  t: (key: string) => key,
}));
vi.mock('@/lib/api', () => ({ api: mocks.api }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: typeof mocks.auth) => unknown) => select(mocks.auth) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: mocks.t, tp: (key: string, count: number) => `${key}:${count}`, lang: 'en' }) }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }));
vi.mock('@/components/ui/ConfirmDialog', () => ({ useConfirm: () => ({ confirm: mocks.confirm, dialog: null }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

import CourseAssignmentsPage from '@/features/course-assignments/CourseAssignmentsPage';
import LearningPathsPage from '@/app/learning-paths/page';
import LearningCyclesPage from '@/app/learning-cycles/page';
import MethodologistWorkbenchPage from '@/app/methodologist-workbench/page';
import { useLanguageStore } from '@/store/languageStore';

const course = { id: 'course', title: 'Synthetic safety course', status: 'published', delivery_type: 'native' };
const learners = [
  { id: 'existing', first_name: 'Existing', last_name: 'Learner', full_name: 'Existing Learner', email: 'existing@example.test', role: 'student' },
  { id: 'new', first_name: 'New', last_name: 'Learner', full_name: 'New Learner', email: 'new@example.test', role: 'student' },
];
const program = { id: 'program', title: 'Synthetic induction program', status: 'published', course_count: 1, assignment_count: 1, courses: [{ course_id: course.id, title: course.title, required: true }] };
const ready = {
  state: 'preview_ready', plan_id: '11111111-1111-4111-8111-111111111111', revision: 2, fingerprint: 'a'.repeat(64), expires_at: '2030-12-31T00:00:00Z',
  course_id: '22222222-2222-4222-8222-222222222222', course_title: 'Safety', release_id: '33333333-3333-4333-8333-333333333333',
  department_id: '44444444-4444-4444-8444-444444444444', department_name: 'Operations', timezone_name: 'Asia/Almaty', due_at: '2030-12-31T17:59:59+05:00',
  notify: false, include_descendants: false,
  recipients: [{ user_id: '55555555-5555-4555-8555-555555555555', label: 'Synthetic learner', already_assigned: false, access_warning: false }], new_count: 1, skipped_count: 0,
};

function panel(name: string) {
  const element = screen.getByRole('heading', { name }).closest('[data-workspace-panel]');
  expect(element).not.toBeNull();
  return element as HTMLElement;
}

function assignmentReads() {
  mocks.fetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    let data: unknown = [];
    if (url.includes('/v1/courses?')) data = [course];
    else if (url.includes('/v1/users?')) data = { users: learners };
    else if (url.endsWith('/v1/courses/course/enrollments')) data = [{ id: 'enrollment', course_id: course.id, user_id: 'existing', source: 'manual', status: 'enrolled', enrolled_at: '2026-11-01T00:00:00Z' }];
    else if (url.endsWith('/personal-link-enrollment') && init?.method === 'POST') data = { enrollment_id: 'new-enrollment', access_url: 'https://example.test/access/synthetic', temporary_pin: '123456', expires_at: '2030-01-01T00:00:00Z' };
    else if (!url.endsWith('/learning-cycles') && !url.endsWith('/learning-cycles/occurrences')) throw new Error(`Unexpected synthetic fetch ${url}`);
    return new Response(JSON.stringify(data), { status: 200 });
  });
}

function managerReads() {
  mocks.api.get.mockImplementation(async (url: string) => {
    if (url === '/v1/learning-paths') return { data: [program] };
    if (url === '/v1/learning-paths/program') return { data: program };
    if (url.endsWith('/assignments')) return { data: [{ id: 'assignment', user_name: 'Existing Learner', status: 'active' }] };
    if (url.startsWith('/v1/courses')) return { data: [course] };
    if (url.includes('role=student')) return { data: { users: learners } };
    return { data: [] };
  });
}

function documentReads(url: string) {
  if (url.includes('/documents/catalog')) return { data: { items: [{ id: 'document', title: 'Synthetic source', version: 2, lifecycle_status: 'active', index: { status: 'ready', revision: 1 } }] } };
  if (url.endsWith('/document-dialogues')) return { data: { tasks: [], has_more: false, next_before: null } };
  throw new Error(`Unexpected synthetic document GET ${url}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, '', '/');
  mocks.auth.user.role = 'methodologist';
  useLanguageStore.getState().setLang('en');
  vi.stubGlobal('fetch', mocks.fetch);
  vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'false');
  vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'false');
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe('delivery rendered compositions', () => {
  it('separates the course toolbar, retained enrollment table and new audience/delivery workspace', async () => {
    assignmentReads();
    window.history.replaceState({}, '', '/assignments?courseId=course');
    render(<CourseAssignmentsPage />);
    const manage = await screen.findByRole('button', { name: 'Current assignments' });
    fireEvent.click(manage);
    await waitFor(() => expect(manage).toHaveAttribute('aria-pressed', 'true'));
    fireEvent.click(await screen.findByRole('button', { name: /Полная таблица|Full table/ }));
    const table = await screen.findByRole('table');
    const existing = panel('courses.enrollments');
    expect(existing).toContainElement(table);
    expect(existing).not.toContainElement(screen.queryByRole('checkbox', { name: 'New Learner' }));
    fireEvent.click(screen.getByRole('button', { name: 'Assign' }));
    const audience = await waitFor(() => panel('courseAssignments.ui.learners'));
    expect(audience).toContainElement(screen.getByRole('checkbox', { name: 'New Learner' }));
    expect(audience).toContainElement(screen.getByRole('group', { name: 'courseAssignments.ui.deliveryLegend' }));
    expect(screen.getByLabelText('courseAssignments.ui.courseLabel').closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(table.parentElement).toHaveClass('overflow-x-auto');
    fireEvent.click(screen.getByRole('checkbox', { name: 'New Learner' }));
    fireEvent.click(screen.getByRole('radio', { name: /^courseAssignments\.ui\.personalLink/ }));
    expect(within(audience).getByLabelText('courseAssignments.ui.linkValidityLabel')).toHaveValue(7);
    expect(mocks.fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('keeps a personal access receipt outside audience controls and retains the exact command payload', async () => {
    assignmentReads();
    window.history.replaceState({}, '', '/assignments?courseId=course');
    render(<CourseAssignmentsPage />);
    fireEvent.click(await screen.findByRole('checkbox', { name: 'New Learner' }));
    fireEvent.click(screen.getByRole('radio', { name: /^courseAssignments\.ui\.personalLink/ }));
    fireEvent.click(screen.getByRole('button', { name: 'courseAssignments.ui.assignCount' }));
    const receipt = await screen.findByRole('heading', { name: 'courseAssignments.ui.personalAccessTitle' });
    const accessPanel = receipt.closest('[data-workspace-panel]');
    expect(accessPanel).toHaveTextContent('PIN: 123456');
    expect(panel('courseAssignments.ui.learners')).not.toContainElement(receipt);
    expect(mocks.confirm).toHaveBeenCalledOnce();
    const post = mocks.fetch.mock.calls.find(([url, init]) => String(url).endsWith('/personal-link-enrollment') && init?.method === 'POST');
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ user_id: 'new', link_expires_at: expect.any(String), completion_window_minutes: null, due_at: null });
  });

  it('keeps a catalogue rail alongside separate stage navigation, working paper and footer commands', async () => {
    managerReads();
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Synthetic induction program/ }));
    const audienceTab = await screen.findByRole('tab', { name: /learningPaths.stage.audience/ });
    expect(audienceTab.closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(panel('learningPaths.programs')).toContainElement(screen.getByRole('button', { name: /Synthetic induction program/ }));
    expect(screen.getByRole('button', { name: 'learningPaths.closeEditor' }).closest('[data-workspace-toolbar]')).not.toBeNull();
    fireEvent.click(audienceTab);
    const settings = screen.getByRole('heading', { name: 'learningPaths.assignmentSettings' }).closest('aside');
    expect(settings).toHaveClass('bg-primary/5');
    expect(panel('learningPaths.currentAssignments')).toHaveTextContent('Existing Learner');
    fireEvent.click(screen.getByRole('checkbox', { name: /New Learner/ }));
    fireEvent.change(screen.getByLabelText('learningPaths.startsAt'), { target: { value: '20/12/2030' } });
    fireEvent.change(screen.getByLabelText('learningPaths.dueAt'), { target: { value: '19/12/2030' } });
    expect(screen.getByRole('button', { name: 'learningPaths.assign' })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('learningPaths.invalidAssignmentDates');
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  it('retains learner sequence, factual progress and locked-course navigation fences', async () => {
    mocks.auth.user.role = 'student';
    mocks.api.get.mockResolvedValue({ data: [{ ...program, progress_percent: 50, completed_required_courses: 1, total_required_courses: 2, steps: [
      { course_id: 'completed', title: 'Completed step', required: true, state: 'completed' },
      { course_id: 'locked', title: 'Locked step', required: true, state: 'locked' },
    ] }] });
    render(<LearningPathsPage />);
    const programPanel = await screen.findByRole('heading', { name: program.title });
    const body = within(programPanel.closest('[data-workspace-panel]') as HTMLElement);
    expect(body.getByText('50%')).toBeInTheDocument();
    expect(body.getAllByRole('listitem').map((item) => item.textContent)).toEqual([expect.stringContaining('Completed step'), expect.stringContaining('Locked step')]);
    expect(body.getByRole('link')).toHaveAttribute('href', '/courses/completed');
    expect(body.queryByRole('link', { name: 'learningPaths.startCourse' })).not.toBeInTheDocument();
  });

  it('puts cycle operations and history before the create disclosure and rule workspace', async () => {
    mocks.api.get.mockImplementation(async (url: string) => ({ data: url === '/v1/users' ? { users: learners } : url.startsWith('/v1/courses') ? [course] : [] }));
    const { container } = render(<LearningCyclesPage />);
    await screen.findByText('learningCycles.emptyHistory');
    const page = container.querySelector('[data-redesign-page="learning-cycles"]') as HTMLElement;
    const surfaces = Array.from(page.children);
    expect(surfaces[1]).toBe(panel('learningCycles.attentionTitle'));
    expect(surfaces[2]).toBe(panel('learningCycles.historyTitle'));
    const disclosure = page.querySelector('details') as HTMLDetailsElement;
    expect(surfaces[3]).toBe(disclosure);
    expect(disclosure.open).toBe(false);
    expect(surfaces[4]).toBe(panel('learningCycles.rulesTitle'));
    fireEvent.click(within(disclosure).getByText('learningCycles.createTitle'));
    expect(disclosure.open).toBe(true);
    expect(within(disclosure).getByRole('button', { name: 'learningCycles.createDraft' })).toBeDisabled();
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  it('does not render a confirmed cycle no-attention state while its read is pending', async () => {
    let resolveRead!: (value: { data: unknown[] }) => void;
    mocks.api.get.mockImplementation((url: string) => url === '/v1/learning-cycles' ? new Promise((resolve) => { resolveRead = resolve; }) : Promise.resolve({ data: url === '/v1/users' ? { users: [] } : [] }));
    render(<LearningCyclesPage />);
    expect(within(panel('learningCycles.attentionTitle')).getByText('common.loading')).toBeInTheDocument();
    expect(screen.queryByText('learningCycles.noAttention')).not.toBeInTheDocument();
    await act(async () => resolveRead({ data: [] }));
    expect(await screen.findByText('learningCycles.noAttention')).toBeInTheDocument();
  });

  it.each([[true, true], [true, false], [false, true], [false, false]])('renders one workbench page heading with assignment=%s, document=%s', async (assignment, document) => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', String(assignment));
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', String(document));
    mocks.api.get.mockImplementation(async (url: string) => documentReads(url));
    const { container } = render(<MethodologistWorkbenchPage />);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Methodologist workbench');
    expect(Boolean(container.querySelector('[data-redesign-page="assignment-workbench"]'))).toBe(assignment);
    expect(Boolean(container.querySelector('[data-redesign-page="document-workbench"]'))).toBe(document);
    if (document) await screen.findByText('Synthetic source');
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  it('gives source selection, editable brief and document dialogue independent paper areas', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED', 'true');
    mocks.api.get.mockImplementation(async (url: string) => documentReads(url));
    render(<MethodologistWorkbenchPage />);
    const source = await screen.findByRole('checkbox', { name: /Synthetic source/ });
    const sourcePanel = source.closest('[data-workspace-panel]');
    const goalPanel = screen.getByLabelText('Course goal').closest('[data-workspace-panel]');
    expect(sourcePanel).not.toBe(goalPanel);
    expect(sourcePanel).toContainElement(screen.getByLabelText('Upload document'));
    expect(goalPanel).toContainElement(screen.getByLabelText('Instruction'));
    const dialogue = screen.getByRole('heading', { name: 'Dialogue with documents' }).closest('[data-workspace-panel]');
    expect(dialogue).not.toBe(sourcePanel);
    expect(dialogue).not.toBe(goalPanel);
    expect(screen.getByRole('button', { name: 'Prepare plan' }).closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Prepare plan' })).toBeDisabled();
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  it('keeps recovered assignment preview and unknown-outcome recovery separate from command entry', async () => {
    vi.stubEnv('NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED', 'true');
    window.history.replaceState({}, '', `/methodologist-workbench?plan=${ready.plan_id}&confirming=1`);
    mocks.api.get.mockResolvedValue({ data: ready });
    render(<MethodologistWorkbenchPage />);
    const confirm = await screen.findByRole('button', { name: 'Confirm assignment' });
    const commandPanel = screen.getByLabelText('Assignment command').closest('[data-workspace-panel]');
    const preview = panel('Review assignment');
    expect(preview).toContainElement(confirm);
    expect(preview).not.toBe(commandPanel);
    expect(within(preview).getAllByText('1')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Check result' }).closest('[data-workspace-panel]')).not.toBe(preview);
    expect(screen.getByRole('button', { name: 'Show preview' })).toBeDisabled();
    expect(mocks.api.post).not.toHaveBeenCalled();
    await waitFor(() => expect(mocks.api.get).toHaveBeenCalledOnce());
  });
});
