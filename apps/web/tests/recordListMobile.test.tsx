import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RecordList } from '@/features/workspace-design/RecordList';

afterEach(() => vi.unstubAllGlobals());

describe('mobile record details', () => {
  it.each([1, 50, 100])('returns from record %i to the exact row and scroll position', (number) => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const scroll = vi.fn();
    vi.stubGlobal('scrollTo', scroll);
    vi.stubGlobal('scrollY', 640);
    const records = Array.from({ length: 100 }, (_, index) => ({ id: index + 1 }));
    const { container } = render(<RecordList records={records} getId={(record) => String(record.id)}
      title={(record) => `Course ${record.id}`} detailsLabel="Course details" mobileBackLabel="Back to list"
      renderDetails={(record) => <h2>Details {record.id}</h2>} />);
    const row = screen.getByRole('button', { name: `Course ${number}` });
    fireEvent.click(row);
    expect(screen.getByRole('region', { name: 'Course details' })).toHaveFocus();
    expect(screen.getByRole('heading', { name: `Details ${number}` })).toBeInTheDocument();
    expect(container.querySelector('ul')).toHaveClass('hidden', 'lg:block');
    fireEvent.click(screen.getByRole('button', { name: 'Back to list' }));
    expect(row).toHaveFocus();
    expect(row).toHaveAttribute('aria-pressed', 'true');
    expect(scroll).toHaveBeenLastCalledWith({ top: 640, behavior: 'instant' });
    expect(container.querySelector('ul')).not.toHaveClass('hidden');
  });
});
