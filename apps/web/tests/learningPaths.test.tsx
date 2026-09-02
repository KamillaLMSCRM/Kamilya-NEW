import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LearningPathsPage from '@/app/learning-paths/page';

const auth = vi.hoisted(() => ({ role: 'methodologist' as string }));
const translate = vi.hoisted(() => (key: string, params?: Record<string, string | number>) => key.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name] ?? `{${name}}`)));
const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
}));

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { user: { role: string } | null }) => unknown) => selector({ user: { role: auth.role } }),
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));

vi.mock('@/i18n/useT', () => ({
  useT: () => ({
    t: translate,
    tp: (key: string, count: number) => `${count} ${key}`,
  }),
}));

const courseA = { id: 'course-a', title: 'Course A', status: 'published' };
const courseB = { id: 'course-b', title: 'Course B', status: 'published' };

function setupManager() {
  apiMock.get.mockImplementation((url: string) => {
    if (url === '/v1/learning-paths') return Promise.resolve({ data: [] });
    if (url.startsWith('/v1/courses')) return Promise.resolve({ data: [courseA, courseB] });
    if (url.includes('role=methodologist')) return Promise.resolve({ data: [{ id: 'methodologist-1', full_name: 'Methodologist One' }] });
    return Promise.resolve({ data: [] });
  });
}

describe('learning programs UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.role = 'methodologist';
  });

  it('keeps the manager surface restricted to the methodologist role', async () => {
    auth.role = 'admin';
    render(<LearningPathsPage />);

    expect(await screen.findByText('learningPaths.forbidden')).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it('adds courses into a numbered sequence and moves them with keyboard-accessible controls', async () => {
    setupManager();
    render(<LearningPathsPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/learning-paths'), { timeout: 5000 });
    await waitFor(() => expect(screen.getAllByRole('button', { name: /learningPaths\.new/ }).length).toBeGreaterThan(0), { timeout: 5000 });
    fireEvent.click(screen.getAllByRole('button', { name: /learningPaths\.new/ })[0]);
    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.content/ }));

    const addButtons = screen.getAllByRole('button', { name: /learningPaths\.add/ });
    fireEvent.click(addButtons[0]);
    fireEvent.click(addButtons[1]);

    const sequence = screen.getByText('learningPaths.sequence').parentElement?.parentElement;
    expect(sequence).toBeTruthy();
    expect(within(sequence as HTMLElement).getByText('Course A')).toBeInTheDocument();
    expect(within(sequence as HTMLElement).getByText('Course B')).toBeInTheDocument();

    const courseBRow = within(sequence as HTMLElement).getByText('Course B').closest('li') as HTMLElement;
    fireEvent.click(within(courseBRow).getByRole('button', { name: 'learningPaths.moveUp' }));
    const ordered = Array.from((sequence as HTMLElement).querySelectorAll('li')).map((item) => item.textContent);
    expect(ordered[0]).toContain('Course B');
    expect(ordered[1]).toContain('Course A');
  });

  it('reads department audiences from the paginated department response', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [] });
      if (url.startsWith('/v1/courses')) return Promise.resolve({ data: [courseA] });
      if (url === '/v1/departments') {
        return Promise.resolve({ data: { departments: [{ id: 'department-1', name: 'HR' }], total: 1 } });
      }
      return Promise.resolve({ data: [] });
    });

    render(<LearningPathsPage />);
    await waitFor(() => expect(screen.getAllByRole('button', { name: /learningPaths\.new/ }).length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole('button', { name: /learningPaths\.new/ })[0]);
    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.audience/ }));
    fireEvent.click(screen.getByRole('tab', { name: 'learningPaths.audience.departments' }));

    expect(screen.getByText('HR')).toBeInTheDocument();
    const departmentCheckbox = screen.getByRole('checkbox', { name: 'HR' });
    expect(departmentCheckbox).toBeEnabled();
    fireEvent.click(departmentCheckbox);
    expect(departmentCheckbox).toBeChecked();
  });

  it('publishes a new program and assigns the audience selected in the draft', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [] });
      if (url.startsWith('/v1/courses')) return Promise.resolve({ data: [courseA] });
      if (url.startsWith('/v1/users')) {
        return Promise.resolve({
          data: {
            users: [{
              id: 'learner-1',
              first_name: 'Learner',
              last_name: 'One',
              email: 'learner@example.kz',
            }],
          },
        });
      }
      if (url === '/v1/learning-paths/program-1/assignments') {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: [] });
    });
    apiMock.post.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') {
        return Promise.resolve({
          data: {
            id: 'program-1',
            title: 'Onboarding',
            description: '',
            status: 'draft',
            course_count: 0,
            courses: [],
          },
        });
      }
      if (url === '/v1/learning-paths/program-1/publish') {
        return Promise.resolve({
          data: {
            id: 'program-1',
            title: 'Onboarding',
            description: '',
            status: 'published',
            course_count: 1,
            courses: [{ course_id: 'course-a', title: 'Course A', required: true, order_index: 0 }],
          },
        });
      }
      if (url === '/v1/learning-paths/program-1/assignments') {
        return Promise.resolve({ data: { created: 1 } });
      }
      return Promise.reject(new Error(`Unexpected POST ${url}`));
    });
    apiMock.put.mockResolvedValue({
      data: {
        id: 'program-1',
        title: 'Onboarding',
        description: '',
        status: 'draft',
        course_count: 1,
        courses: [{ course_id: 'course-a', title: 'Course A', required: true, order_index: 0 }],
      },
    });

    render(<LearningPathsPage />);
    await waitFor(() => expect(screen.getAllByRole('button', { name: /learningPaths\.new/ }).length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByRole('button', { name: /learningPaths\.new/ })[0]);
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Onboarding' } });

    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.content/ }));
    fireEvent.click((await screen.findAllByRole('button', { name: /learningPaths\.add/ }))[0]);

    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.audience/ }));
    const learnerCheckbox = screen.getByRole('checkbox', { name: /Learner One/ });
    expect(learnerCheckbox).toBeEnabled();
    fireEvent.click(learnerCheckbox);

    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.review/ }));
    const publishButton = screen.getByRole('button', { name: 'learningPaths.publishAndAssign' });
    expect(publishButton).toBeEnabled();
    fireEvent.click(publishButton);

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledWith('/v1/learning-paths/program-1/publish');
      expect(apiMock.post).toHaveBeenCalledWith(
        '/v1/learning-paths/program-1/assignments',
        expect.objectContaining({ user_ids: ['learner-1'] }),
      );
    });
  });

  it('keeps publish disabled until the draft has a name and a required course', async () => {
    setupManager();
    render(<LearningPathsPage />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/learning-paths'), { timeout: 5000 });
    await waitFor(() => expect(screen.getAllByRole('button', { name: /learningPaths\.new/ }).length).toBeGreaterThan(0), { timeout: 5000 });
    fireEvent.click(screen.getAllByRole('button', { name: /learningPaths\.new/ })[0]);
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Onboarding' } });
    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.review/ }));

    expect(screen.getByRole('button', { name: /learningPaths\.publish/ })).toBeDisabled();

    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.content/ }));
    fireEvent.click((await screen.findAllByRole('button', { name: /learningPaths\.add/ }))[0]);
    fireEvent.click(screen.getByRole('checkbox', { name: 'learningPaths.required' }));
    apiMock.post.mockResolvedValue({ data: { id: 'program-1', title: 'Onboarding', description: '', status: 'draft', course_count: 0 } });
    apiMock.put.mockImplementation((_url: string, body: { steps: Array<{ course_id: string; required: boolean }> }) => Promise.resolve({
      data: {
        id: 'program-1',
        title: 'Onboarding',
        description: '',
        status: 'draft',
        course_count: body.steps.length,
        courses: body.steps.map((step, index) => ({ ...step, title: 'Course A', order_index: index })),
      },
    }));
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/v1/learning-paths/program-1/curriculum', expect.anything()));
    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.review/ }));
    expect(screen.getByRole('button', { name: /learningPaths\.publish/ })).toBeDisabled();

    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.content/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'learningPaths.required' }));
    fireEvent.click(screen.getByRole('tab', { name: /learningPaths\.stage\.review/ }));
    expect(screen.getByRole('button', { name: /learningPaths\.publish/ })).toBeEnabled();
  });

  it('renders only assigned learner programs and links available or completed steps', async () => {
    auth.role = 'student';
    apiMock.get.mockResolvedValue({
      data: [{
        id: 'program-1',
        title: 'Onboarding',
        total_required_courses: 2,
        completed_required_courses: 1,
        steps: [
          { course_id: 'course-a', title: 'Finished course', required: true, state: 'completed' },
          { course_id: 'course-b', title: 'Current course', required: true, state: 'available' },
          { course_id: 'course-c', title: 'Locked course', required: false, state: 'locked' },
        ],
      }],
    });
    render(<LearningPathsPage />);

    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    expect(screen.getByRole('heading', { name: 'Onboarding' })).toBeInTheDocument();
    expect(screen.getByText('1 из 2 common.counts.courseTotal · learningPaths.required')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'learningPaths.reviewCourse' })).toHaveAttribute('href', '/courses/course-a');
    expect(screen.getByRole('link', { name: 'learningPaths.startCourse' })).toHaveAttribute('href', '/courses/course-b');
    expect(screen.queryByRole('link', { name: /Locked course/ })).not.toBeInTheDocument();
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/learning-paths/my'));
  });

  it('loads active methodologists and renders the responsible selector', async () => {
    setupManager();
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [] });
      if (url.startsWith('/v1/courses')) return Promise.resolve({ data: [] });
      if (url.includes('role=methodologist')) return Promise.resolve({ data: [{ id: 'methodologist-1', full_name: 'Methodologist One', email: 'methodologist@example.kz' }] });
      return Promise.resolve({ data: [] });
    });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /learningPaths\.new/ }));
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/v1/users?role=methodologist&is_active=true&per_page=500'));
    expect(screen.getByRole('option', { name: /Methodologist One/ })).toBeInTheDocument();
  });

  it('hydrates responsible methodologist and default due period from an existing draft', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [{ id: 'program-1', title: 'Draft', status: 'draft', course_count: 0 }] });
      if (url === '/v1/learning-paths/program-1') return Promise.resolve({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [], responsible_user_id: 'methodologist-1', default_due_days: 30 } });
      if (url.endsWith('/assignments')) return Promise.resolve({ data: [] });
      if (url.includes('role=methodologist')) return Promise.resolve({ data: [{ id: 'methodologist-1', full_name: 'Methodologist One' }] });
      return Promise.resolve({ data: [] });
    });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Draft/ }));
    expect(await screen.findByRole('option', { name: 'Methodologist One' })).toBeInTheDocument();
    expect(screen.getByDisplayValue('30')).toBeInTheDocument();
  });

  it('persists both draft settings in create and update payloads, including blank due days as null', async () => {
    setupManager();
    apiMock.post.mockResolvedValue({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [], responsible_user_id: 'methodologist-1', default_due_days: null } });
    apiMock.put.mockResolvedValue({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [], responsible_user_id: 'methodologist-1', default_due_days: null } });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /learningPaths\.new/ }));
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Draft' } });
    fireEvent.change(screen.getByLabelText('learningPaths.responsibleMethodologist'), { target: { value: 'methodologist-1' } });
    const dueInput = screen.getByPlaceholderText('learningPaths.defaultDueDaysPlaceholder');
    fireEvent.change(dueInput, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/learning-paths', expect.objectContaining({ responsible_user_id: 'methodologist-1', default_due_days: null })));
    fireEvent.change(dueInput, { target: { value: '45' } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/v1/learning-paths/program-1', expect.objectContaining({ responsible_user_id: 'methodologist-1', default_due_days: 45 })));
  });

  it.each(['0', '3651', '1.5'])('blocks save for invalid default due days value %s', async (value) => {
    setupManager();
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /learningPaths\.new/ }));
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Draft' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.defaultDueDaysPlaceholder'), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it('keeps legacy drafts without the new fields usable', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [{ id: 'legacy', title: 'Legacy', status: 'draft', course_count: 0 }] });
      if (url === '/v1/learning-paths/legacy') return Promise.resolve({ data: { id: 'legacy', title: 'Legacy', status: 'draft', course_count: 0, courses: [] } });
      if (url.endsWith('/assignments')) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Legacy/ }));
    expect(await screen.findByDisplayValue('Legacy')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('learningPaths.defaultDueDaysPlaceholder')).toBeInTheDocument();
  });

  it('persists certificate and periodic knowledge refresh policies', async () => {
    setupManager();
    apiMock.post.mockResolvedValue({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [] } });
    apiMock.put.mockResolvedValue({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [] } });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /learningPaths\.new/ }));
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Draft' } });
    fireEvent.change(screen.getByLabelText('learningPaths.certificatePolicy'), { target: { value: 'final_course' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.certificateValidityPlaceholder'), { target: { value: '12' } });
    fireEvent.change(screen.getByLabelText('learningPaths.knowledgeRefresh'), { target: { value: 'fixed_interval_after_completion' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.refreshEveryDaysPlaceholder'), { target: { value: '365' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.refreshDueDaysPlaceholder'), { target: { value: '21' } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/v1/learning-paths', expect.objectContaining({
      certificate_mode: 'final_course',
      certificate_validity_months: 12,
      recurrence_mode: 'fixed_interval_after_completion',
      recurrence_cadence_days: 365,
      recurrence_due_days: 21,
    })));
  });

  it('hydrates policy fields and normalizes disabled policies to null dependents', async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === '/v1/learning-paths') return Promise.resolve({ data: [{ id: 'program-1', title: 'Draft', status: 'draft', course_count: 0 }] });
      if (url === '/v1/learning-paths/program-1') return Promise.resolve({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [], certificate_mode: 'final_course', certificate_validity_months: 24, recurrence_mode: 'fixed_interval_after_completion', recurrence_cadence_days: 180, recurrence_due_days: 14 } });
      if (url.endsWith('/assignments')) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    apiMock.put.mockResolvedValue({ data: { id: 'program-1', title: 'Draft', status: 'draft', course_count: 0, courses: [] } });
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Draft/ }));
    expect(await screen.findByDisplayValue('24')).toBeInTheDocument();
    expect(screen.getByDisplayValue('180')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('learningPaths.certificatePolicy'), { target: { value: 'none' } });
    fireEvent.change(screen.getByLabelText('learningPaths.knowledgeRefresh'), { target: { value: 'none' } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/v1/learning-paths/program-1', expect.objectContaining({
      certificate_mode: 'none',
      certificate_validity_months: null,
      recurrence_mode: 'none',
      recurrence_cadence_days: null,
      recurrence_due_days: null,
    })));
  });

  it('blocks inconsistent periodic knowledge refresh settings', async () => {
    setupManager();
    render(<LearningPathsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /learningPaths\.new/ }));
    fireEvent.change(screen.getByLabelText('learningPaths.name'), { target: { value: 'Draft' } });
    fireEvent.change(screen.getByLabelText('learningPaths.knowledgeRefresh'), { target: { value: 'fixed_interval_after_completion' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.refreshEveryDaysPlaceholder'), { target: { value: '30' } });
    fireEvent.change(screen.getByPlaceholderText('learningPaths.refreshDueDaysPlaceholder'), { target: { value: '45' } });
    fireEvent.click(screen.getByRole('button', { name: 'learningPaths.saveDraft' }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});
