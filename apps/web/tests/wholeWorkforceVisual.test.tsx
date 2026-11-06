import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ComponentType } from 'react';

const mocks = vi.hoisted(() => {
  const t = (key: string) => key;
  return {
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn() },
    t,
    tp: (key: string, count: number) => `${key}:${count}`,
    router: { replace: vi.fn(), push: vi.fn() },
    auth: { accessToken: 'synthetic', user: { role: 'methodologist', tenant_id: 'tenant', user_id: 'actor', tenant: { is_demo: false } } },
  };
});
vi.mock('@/lib/api', () => ({ api: mocks.api }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: typeof mocks.auth) => unknown) => select(mocks.auth) }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: mocks.t, tp: mocks.tp, lang: 'en' }) }));
vi.mock('next/navigation', () => ({
  useRouter: () => mocks.router,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import PositionsPage from '@/app/positions/page';
import { PositionQualificationCard } from '@/features/positions/PositionQualificationCard';
import { StaffWorkspace } from '@/features/staff-structure/StaffWorkspace';
import CohortsPage from '@/app/cohorts/page';
import CompetenciesPage from '@/app/competencies/page';
import InvitationsPage from '@/app/admin/invitations/page';
import CandidateAssessmentsPage from '@/app/candidate-assessments/page';

let StaffPage: ComponentType;
beforeAll(async () => {
  vi.stubEnv('NEXT_PUBLIC_STAFF_STRUCTURE_V3_ENABLED', 'false');
  StaffPage = (await import('@/app/admin/staff/page')).default;
});
afterAll(() => vi.unstubAllEnvs());
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/staff');
});

function reads(routes: Record<string, unknown>) {
  mocks.api.get.mockImplementation(async (url: string) => {
    if (!(url in routes)) throw new Error(`Unexpected synthetic GET ${url}`);
    return { data: routes[url] };
  });
}

function panelFor(heading: string) {
  const panel = screen.getByRole('heading', { name: heading }).closest('[data-workspace-panel]');
  expect(panel).not.toBeNull();
  return within(panel as HTMLElement);
}

const position = {
  id: 'position', name: 'Synthetic operator with a long catalogue name', department: 'Operations',
  department_id: 'unit', level: 'L1', course_ids: ['course'], employee_count: 4,
  instruction_document_id: null, instruction_filename: null, instruction_embedding_status: null,
};
const unit = {
  id: 'unit', name: 'Operations', parent_id: null, unit_type: 'department', is_active: true,
  is_head_office: false, head_user_id: null, breadcrumb: ['Operations'], direct_count: 4,
  subtree_count: 4, hr_managed: false,
};

describe('workforce rendered page compositions', () => {
  it('places staff import stages, file selection and manual action in distinct task areas', async () => {
    window.history.replaceState({}, '', '/staff?tab=import');
    reads({
      '/v1/admin/staff/import/mappings': [], '/v1/departments': { departments: [] },
      '/v1/positions': [], '/v1/organization-units/tree': { roots: [] },
    });
    const { container } = render(<StaffPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'staffPage.title' })).toBeInTheDocument();
    expect(container.querySelector('[data-workspace-actions]')).toContainElement(screen.getByRole('button', { name: 'authenticatedUi.adminStaff.manual.addEmployee' }));
    expect(screen.getByRole('tablist').closest('[data-workspace-toolbar]')).not.toBeNull();
    const flow = panelFor('authenticatedUi.adminStaff.import.title');
    expect(flow.getByRole('list')).toHaveClass('xl:grid-cols-5');
    expect(flow.getAllByRole('listitem')).toHaveLength(5);
    expect(flow.getByRole('button', { name: 'authenticatedUi.adminStaff.import.startAnalysis' })).toBeDisabled();
    expect(flow.getByRole('option', { name: 'authenticatedUi.adminStaff.import.modeFullReconciliation' })).toBeDisabled();
    await waitFor(() => expect(mocks.api.get).toHaveBeenCalledWith('/v1/admin/staff/import/mappings'));
    fireEvent.click(screen.getByRole('button', { name: 'authenticatedUi.adminStaff.manual.addEmployee' }));
    const manual = within(screen.getByRole('dialog'));
    expect(manual.getByRole('group', { name: 'authenticatedUi.adminStaff.manual.newEmployee' })).toHaveClass('bg-muted/30');
    expect(manual.getByRole('group', { name: 'staffPage.tabs.structure' })).toHaveClass('border');
    await waitFor(() => expect(mocks.api.get).toHaveBeenCalledWith('/v1/departments'));
  });

  it('keeps fallback structure search and commands in a toolbar above the retained tree', async () => {
    reads({
      '/v1/admin/staff/import/mappings': [],
      '/v1/admin/staff/structure': { roots: [{ ...unit, children: [], positions: [] }], summary: { total_employees: 4, total_departments: 1, total_positions: 1 } },
    });
    const { container } = render(<StaffPage />);
    const search = await screen.findByRole('searchbox');
    expect(search.closest('[data-workspace-toolbar]')).toContainElement(screen.getByRole('button', { name: 'authenticatedUi.adminStaff.structure.addBranch' }));
    expect(container.querySelectorAll('[data-workspace-stat]')).toHaveLength(4);
    expect(screen.getByRole('heading', { name: 'Структура организации' })).toBeInTheDocument();
  });

  it('composes V3 schema, contextual detail and URL-backed roster without changing data owners', async () => {
    reads({
      '/v1/organization-units/workspace': { units: [unit], positions: [], total: 4, unplaced_count: 0 },
      '/v1/organization-units/employees': { items: [], total: 0, page: 1, page_size: 20 },
    });
    render(<StaffWorkspace refreshKey={0} onAddEmployee={vi.fn()} onEditEmployee={vi.fn()} onEditUnit={vi.fn()} onAddUnit={vi.fn()} />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Структура' }));
    const open = await screen.findByRole('button', { name: 'Открыть подразделение: Operations' });
    expect(screen.getByRole('tablist', { name: 'Представление структуры' }).closest('[data-workspace-toolbar]')).toContainElement(screen.getByRole('button', { name: 'Добавить подразделение' }));
    expect(panelFor('Схема подразделений').getByRole('button', { name: 'Открыть подразделение: Operations' })).toBe(open);
    fireEvent.click(open);
    expect(await screen.findByRole('tablist', { name: 'Содержимое подразделения' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Список' }));
    expect(await screen.findByLabelText('authenticatedUi.staffWorkspaceSearch.searchLabel')).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('staff_unit')).toBe('unit');
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  it('renders a searchable position card catalogue with scoped record facts and footer navigation', async () => {
    reads({ '/v1/positions': [position], '/v1/organization-units/tree': { roots: [] } });
    const { container } = render(<PositionsPage />);
    const link = await screen.findByRole('link', { name: new RegExp(position.name) });
    expect(link.parentElement).toHaveClass('md:grid-cols-2');
    expect(within(link).getByText('authenticatedUi.positions.openCard')).toHaveClass('border-t');
    const search = screen.getByRole('textbox', { name: 'authenticatedUi.positions.searchLabel' });
    expect(search.closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(container.querySelector('[data-workspace-actions]')).toContainElement(screen.getByRole('button', { name: 'positions.create' }));
    fireEvent.change(search, { target: { value: 'missing' } });
    expect(screen.getByText('authenticatedUi.positions.noSearchResults')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: new RegExp(position.name) })).not.toBeInTheDocument();
  });

  it('separates position detail navigation, honest stats and the editable profile panel', async () => {
    reads({
      '/v1/positions/position/qualification-card': {
        profile: { ...position, responsibilities: 'Operate safely', requirements: 'Induction' },
        instruction: null, competencies: [], training: { position_courses: [], effective_courses: [] },
        employees: { active_count: 4 }, latest_version: null, onboarding_quiz: null,
      },
      '/v1/competencies': [], '/v1/courses?per_page=100': { items: [] },
    });
    const { container } = render(<PositionQualificationCard positionId="position" />);
    await screen.findByRole('heading', { level: 1, name: position.name });
    expect(container.querySelectorAll('[data-workspace-stat]')).toHaveLength(4);
    const nav = screen.getByRole('navigation', { name: 'authenticatedUi.positions.cardSectionsAria' });
    expect(nav).toHaveClass('xl:sticky');
    expect(within(nav).getByRole('button', { name: 'authenticatedUi.positions.tabs.profile' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByDisplayValue('Operate safely').closest('[data-workspace-panel]')).not.toBeNull();
    fireEvent.click(within(nav).getByRole('button', { name: 'authenticatedUi.positions.tabs.training' }));
    expect(mocks.router.replace).toHaveBeenCalledWith('/positions/position?tab=training', { scroll: false });
  });

  it('separates cohort catalogue, identity editor and eligible member panel', async () => {
    const cohort = { id: 'cohort', name: 'Operations cohort', description: '', member_count: 1, responsible_user_id: null, responsible_user_name: null };
    reads({
      '/v1/cohorts': [cohort], '/v1/cohorts/cohort': { ...cohort, user_ids: ['student'] },
      '/v1/users?per_page=500&role=student&is_active=true': { users: [{ id: 'student', first_name: 'Synthetic', last_name: 'Learner', role: 'student', is_active: true }] },
      '/v1/users?per_page=500&role=methodologist&is_active=true': { users: [] },
    });
    render(<CohortsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Operations cohort/ }));
    const member = await screen.findByRole('checkbox', { name: 'Synthetic Learner' });
    expect(member).toBeChecked();
    expect(panelFor('cohorts.members').getByRole('checkbox', { name: 'Synthetic Learner' })).toBe(member);
    expect(panelFor('Operations cohort').getByLabelText('cohorts.name')).toHaveValue('Operations cohort');
    expect(screen.queryByRole('checkbox', { name: /course/i })).not.toBeInTheDocument();
  });

  it('keeps cohort loading and retry states distinct from an empty catalogue', async () => {
    mocks.api.get.mockRejectedValue(new Error('Synthetic unavailable'));
    render(<CohortsPage />);
    expect(screen.getByRole('status')).toHaveTextContent('common.loading');
    expect(await screen.findByRole('alert')).toHaveTextContent('cohorts.loadFailed');
    expect(screen.getByRole('button', { name: 'common.retry' }).closest('[data-workspace-panel]')).not.toBeNull();
    expect(screen.queryByText('cohorts.empty')).not.toBeInTheDocument();
  });

  it('keeps competency identity, read-only positions and selectable course links in separate panels', async () => {
    const competency = { id: 'competency', name: 'Safe operations', description: '', position_count: 1, course_count: 1 };
    reads({
      '/v1/competencies': [competency], '/v1/positions': [position], '/v1/courses': [{ id: 'course', title: 'Induction' }],
      '/v1/competencies/competency': { ...competency, position_ids: ['position'], course_ids: ['course'] },
    });
    render(<CompetenciesPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Safe operations/ }));
    const positionsPanel = await screen.findByRole('heading', { name: 'Связанные должности' });
    expect(positionsPanel.closest('[data-workspace-panel]')).not.toContainElement(screen.getByRole('checkbox', { name: 'Induction' }));
    expect(panelFor('competencies.courses').getByRole('checkbox', { name: 'Induction' })).toBeChecked();
    expect(screen.getByRole('link', { name: position.name })).toHaveAttribute('href', '/positions/position?tab=competencies');
    expect(panelFor('Safe operations').getByLabelText('competencies.name')).toHaveValue('Safe operations');
  });

  it('distinguishes invitation creation, one-time links and truthful delivery records', async () => {
    const delivery = { email: 'learner@example.test', delivery_status: 'failed', delivery_failure_message: 'Delivery rejected', invite_url: 'https://example.test/invite/opaque' };
    reads({ '/v1/users/invitations?per_page=100': { items: [{ ...delivery, id: 'invite', status: 'pending', expires_at: '2030-01-01' }] } });
    mocks.api.post.mockResolvedValue({ data: { created: [delivery] } });
    render(<InvitationsPage />);
    await screen.findByText('Delivery rejected');
    const createPanel = panelFor('invitations.createTitle');
    fireEvent.change(createPanel.getByRole('textbox', { name: 'invitations.emailLabel' }), { target: { value: 'learner@example.test' } });
    fireEvent.click(createPanel.getByRole('button', { name: 'invitations.createButton' }));
    await screen.findByRole('heading', { name: 'invitations.linksTitle' });
    expect(panelFor('invitations.linksTitle').getByDisplayValue(delivery.invite_url)).toHaveAttribute('readonly');
    expect(panelFor('invitations.listTitle').getByRole('button', { name: 'invitations.resend' })).toBeInTheDocument();
    expect(mocks.api.post).toHaveBeenCalledWith('/v1/users/invitations/bulk', { items: [{ email: 'learner@example.test' }] });
  });

  it('groups released campaign creation, name-only invitation and per-campaign result actions', async () => {
    reads({
      '/v1/candidate-assessments': [{ id: 'campaign', title: 'Operator assessment', status: 'active', expires_at: '2030-01-01' }],
      '/v1/courses?status=published&per_page=100': [{ id: 'course', title: 'Induction', current_release_id: 'release' }],
    });
    render(<CandidateAssessmentsPage />);
    await screen.findByRole('heading', { name: 'Operator assessment' });
    expect(panelFor('Новая кампания').getByRole('combobox', { name: 'Опубликованный курс' })).toBeInTheDocument();
    expect(panelFor('Пригласить кандидата').getByRole('textbox', { name: 'Email кандидата (необязательно)' })).not.toBeRequired();
    const results = panelFor('Operator assessment');
    expect(results.getByRole('button', { name: 'CSV' })).toBeInTheDocument();
    expect(results.getByRole('button', { name: 'Пригласить' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Имя кандидата'), { target: { value: 'Synthetic Candidate' } });
    expect(results.getByRole('button', { name: 'Пригласить' })).toBeEnabled();
  });
});
