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

  it('omits only an exact first heading duplicated by the reader chrome', () => {
    render(<LessonContent text={'# Lesson title\n\nBody\n\n# Lesson title again'} omitFirstHeading="Lesson title" />);

    expect(screen.queryByRole('heading', { level: 1, name: 'Lesson title' })).not.toBeInTheDocument();
    expect(screen.getByText('Body')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Lesson title again' })).toBeInTheDocument();
  });

  it('keeps the heading in default authoring previews', () => {
    render(<LessonContent text={'# Lesson title\n\nBody'} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Lesson title' })).toBeInTheDocument();
  });

  it('preserves different titles and lower-level headings even with reader suppression', () => {
    const { rerender } = render(<LessonContent text={'# Different title\n\nBody'} omitFirstHeading="Lesson title" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Different title' })).toBeInTheDocument();
    rerender(<LessonContent text={'## Lesson title\n\nBody'} omitFirstHeading="Lesson title" />);
    expect(screen.getByRole('heading', { level: 2, name: 'Lesson title' })).toBeInTheDocument();
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

  it('preserves source ordinals for ordered steps, including marker styles and heading-separated lists', () => {
    const { container } = render(
      <LessonContent
        text={'### Шаг 2\n\n2. Start here\n3) Continue\n\n### Шаг 10\n\n10. Final step'}
      />,
    );

    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(2);
    expect(lists[0]).toHaveAttribute('start', '2');
    expect(lists[0].querySelectorAll('li')[0]).not.toHaveAttribute('value');
    expect(lists[1]).toHaveAttribute('start', '10');
    expect(container.querySelectorAll('li')[0]).toHaveTextContent('Start here');
    expect(container.querySelectorAll('li')[1]).toHaveTextContent('Continue');
    expect(container.querySelectorAll('li')[2]).toHaveTextContent('Final step');
  });

  it('preserves explicit nonconsecutive ordered values', () => {
    render(<LessonContent text={'0) Zero\n2. Two\n10) Ten'} />);

    const list = screen.getByRole('list');
    expect(list).toHaveAttribute('start', '0');
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveAttribute('value', '0');
    expect(items[1]).toHaveAttribute('value', '2');
    expect(items[2]).toHaveAttribute('value', '10');
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

  it('renders backend-escaped fallback punctuation literally without creating Markdown structure', () => {
    const { container } = render(
      <LessonContent
        text={'Руководитель обязан:\n\n\\- организовать проверку;\n\\- назначить ответственного.\n\nСрок: \\(в течение 2 дней\\).'}
      />,
    );

    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('- организовать проверку;') === true)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('- назначить ответственного.') === true)).toBeInTheDocument();
    expect(screen.getByText('Срок: (в течение 2 дней).')).toBeInTheDocument();
    expect(container.querySelectorAll('ul, ol, h1, h2, h3, h4, h5, h6')).toHaveLength(0);
  });

  it('keeps escaped emphasis, code, headings, links, HTML, and source backslashes inert', () => {
    const { container } = render(
      <LessonContent
        text={'\\*\\*Не форматировать\\*\\* \\`not code\\` \\# heading \\[bad\\](https://evil.example/?x=1)\n\n<img src=x onerror=alert(1)>\n\nPath: C:\\\\tmp\\\\file'}
      />,
    );

    expect(screen.getByText('**Не форматировать** `not code` # heading [bad](https://evil.example/?x=1)')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('Path: C:\\tmp\\file')).toBeInTheDocument();
    expect(container.querySelectorAll('strong, em, code, a, img, h1, h2, h3, h4, h5, h6')).toHaveLength(0);
  });

  it('preserves literal escapes and a trailing backslash inside real inline code', () => {
    render(<LessonContent text={'`\\*literal\\*` and `C:\\tmp\\`'} />);
    const code = screen.getAllByText((_, element) => element?.tagName === 'CODE');
    expect(code.map((element) => element.textContent)).toEqual(['\\*literal\\*', 'C:\\tmp\\']);
  });
});
