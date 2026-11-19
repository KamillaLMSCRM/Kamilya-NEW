import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useCourseLanguage } from '@/features/course-authoring/useCourseLanguage';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: apiMock }));

describe('course language preference', () => {
  it('keeps the lesson and the choice across interface changes, scoped to the learner', async () => {
    localStorage.clear();
    apiMock.get.mockImplementation((_path, { params }) => Promise.resolve({
      data: {
        primary: 'ru',
        available: ['ru', 'kk'],
        content: params.language === 'kk' ? { 'lesson.lesson-1.title': 'Нұсқаулық' } : {},
      },
    }));
    const { result, rerender } = renderHook(
      ({ identity, lang }) => useCourseLanguage('course-1', identity, lang),
      { initialProps: { identity: 'tenant:learner-one', lang: 'ru' } },
    );
    await waitFor(() => expect(result.current.language).toBe('ru'));
    act(() => result.current.choose('kk'));
    await waitFor(() => expect(result.current.language).toBe('kk'));
    expect(result.current.text('lesson', 'lesson-1', 'title', 'Инструкция')).toBe('Нұсқаулық');
    rerender({ identity: 'tenant:learner-one', lang: 'en' });
    expect(result.current.language).toBe('kk');
    rerender({ identity: 'tenant:learner-two', lang: 'ru' });
    await waitFor(() => expect(result.current.language).toBe('ru'));
    expect(localStorage.getItem('course-language:tenant:learner-two:course-1')).toBeNull();
  });
});
