import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CompetenciesPage from '@/app/competencies/page';
import { api } from '@/lib/api';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { role: 'methodologist' } }) }));
vi.mock('@/i18n/useT', () => {
  const t = (key: string) => key;
  const tp = (key: string, count: number) => `${key}:${count}`;
  return { useT: () => ({ t, tp }) };
});

const mocks = vi.mocked(api);
let saved: { id: string; name: string; description: string; position_count: number; course_count: number; position_ids: string[]; course_ids: string[] } | null;
const course = { id: 'course-owned', title: 'Owned QA course' };

beforeEach(() => {
  vi.clearAllMocks();
  saved = null;
  mocks.get.mockImplementation(async (url) => {
    if (url === '/v1/competencies') return { data: saved ? [saved] : [] } as never;
    if (url === '/v1/positions') return { data: [] } as never;
    if (url === '/v1/courses') return { data: [course] } as never;
    if (url === '/v1/competencies/owned') return { data: saved } as never;
    throw new Error(`Unexpected GET ${url}`);
  });
  mocks.post.mockImplementation(async () => {
    saved = { id: 'owned', name: 'QA competency', description: '', position_count: 0, course_count: 0, position_ids: [], course_ids: [] };
    return { data: saved } as never;
  });
  mocks.put.mockImplementation(async (_url, body) => {
    const links = body as { course_ids: string[] };
    saved = { ...saved!, course_ids: links.course_ids, course_count: links.course_ids.length };
    return { data: saved } as never;
  });
  mocks.patch.mockResolvedValue({ data: {} } as never);
});

async function prepare() {
  render(<CompetenciesPage />);
  await screen.findByRole('checkbox', { name: course.title });
  fireEvent.change(screen.getByLabelText('competencies.name'), { target: { value: 'QA competency' } });
  fireEvent.click(screen.getByRole('checkbox', { name: course.title }));
  fireEvent.click(screen.getByRole('button', { name: 'competencies.create' }));
}

describe('competency creation with selected courses', () => {
  it('does not write links when no courses were selected', async () => {
    render(<CompetenciesPage />);
    await screen.findByRole('checkbox', { name: course.title });
    fireEvent.change(screen.getByLabelText('competencies.name'), { target: { value: 'QA competency' } });
    fireEvent.click(screen.getByRole('button', { name: 'competencies.create' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'competencies.save' })).toBeEnabled());
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('persists the selected course before reloading the created detail', async () => {
    await prepare();
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/v1/competencies/owned/links', { position_ids: [], course_ids: ['course-owned'] }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'competencies.save' })).toBeEnabled());
    expect(screen.getByRole('checkbox', { name: course.title })).toBeChecked();
    expect(saved?.course_ids).toEqual(['course-owned']);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('retains the created identity and selection after a link failure, avoiding duplicate create', async () => {
    mocks.put.mockRejectedValueOnce(new Error('temporary link failure'));
    await prepare();
    await waitFor(() => expect(screen.getByRole('button', { name: 'competencies.save' })).toBeEnabled());
    expect(screen.getByRole('checkbox', { name: course.title })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'competencies.save' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(saved?.course_ids).toEqual(['course-owned']);
  });
});
