import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LessonContent } from '../src/features/course-authoring/LessonContent';

describe('LessonContent', () => {
  it('renders Markdown headings without visible marker characters', () => {
    render(<LessonContent text={'## A useful heading\n\n### Smaller heading'} />);

    expect(screen.getByRole('heading', { level: 2, name: 'A useful heading' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Smaller heading' })).toBeInTheDocument();
    expect(screen.queryByText(/##/)).not.toBeInTheDocument();
  });

  it('renders semantic lists and a simple pipe table', () => {
    render(
      <LessonContent
        text={'- First\n- Second\n\n1. One\n2. Two\n\n| Name | Value |\n| --- | --- |\n| Alpha | 1 |'}
      />,
    );

    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(2);
    expect(lists[0].tagName).toBe('UL');
    expect(lists[1].tagName).toBe('OL');
    expect(screen.getAllByRole('listitem')).toHaveLength(4);

    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Name' })).toBeInTheDocument();
    expect(within(table).getByRole('cell', { name: '1' })).toBeInTheDocument();
  });

  it('renders paragraphs, blockquotes, bold, italic, and inline code semantically', () => {
    const { container } = render(
      <LessonContent text={'A **bold** and *italic* paragraph with `code`.\n\n> A quoted idea'} />,
    );

    expect(screen.getByText('bold').tagName).toBe('STRONG');
    expect(screen.getByText('italic').tagName).toBe('EM');
    expect(screen.getByText('code').tagName).toBe('CODE');
    expect(container.querySelector('p')).toHaveTextContent('A bold and italic paragraph with code.');
    expect(container.querySelector('blockquote')).toHaveTextContent('A quoted idea');
  });

  it('keeps raw HTML inert and malformed markup readable', () => {
    const { container } = render(
      <LessonContent text={'<img src=x onerror=alert(1)>\n\n**unfinished markup'} />,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('**unfinished markup')).toBeInTheDocument();
  });
});
