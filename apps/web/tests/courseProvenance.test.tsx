import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CourseProvenance } from '@/features/course-catalog/CourseProvenance';

describe('Saved course provenance', () => {
  it('shows recorded author and two distinct saved timestamps', () => {
    render(<CourseProvenance lang="ru" authorName="Тестовый методист" createdAt="2026-11-01T10:00:00Z" updatedAt="2026-11-13T05:00:00Z" />);
    expect(screen.getByText('Тестовый методист')).toBeInTheDocument();
    expect(screen.getByText(/1 нояб.*15:00/)).toBeInTheDocument();
    expect(screen.getByText(/13 нояб.*10:00/)).toBeInTheDocument();
  });

  it('does not invent an author or date for legacy records', () => {
    render(<CourseProvenance lang="ru" authorName=" " createdAt="invalid" />);
    expect(screen.getByText('Не указан')).toBeInTheDocument();
    expect(screen.getAllByText('Нет данных')).toHaveLength(2);
  });
});
