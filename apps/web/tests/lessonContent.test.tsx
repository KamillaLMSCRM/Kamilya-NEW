import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LessonContent } from '../src/features/course-authoring/LessonContent';

describe('LessonContent', () => {
  it('renders a single-column table and its literal pipes without changing cell boundaries', () => {
    render(<LessonContent text={'Summary\n| Action |\n| --- |\n| **A** \\| B |\nAfter'} />);
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('columnheader')).toHaveLength(1);
    expect(within(table).getAllByRole('cell')).toHaveLength(1);
    expect(within(table).getByRole('cell')).toHaveTextContent('A | B');
    expect(within(table).getByText('A').tagName).toBe('STRONG');
    expect(screen.getByText('After')).toBeVisible();
  });
  it('renders independent collapsed hints and examples with formatted, inert content', () => {
    const { container } = render(<LessonContent text={[
      'Lesson introduction', ':::lesson-hint Read <b>carefully</b>', '**Important**', '',
      '1. Read the panel', '2. Record the result', ':::end-lesson-disclosure', '',
      ':::lesson-example Exercise', 'An example response', ':::end-lesson-disclosure', 'Conclusion',
    ].join('\n')} />);
    const details = container.querySelectorAll('details');
    expect(details).toHaveLength(2);
    expect(details[0]).not.toHaveAttribute('open');
    expect(details[1]).not.toHaveAttribute('open');
    expect(within(details[0]).getByText('Read <b>carefully</b>')).toBeInTheDocument();
    expect(within(details[0]).getByText('Important').tagName).toBe('STRONG');
    expect(details[0].querySelector('ol')?.children).toHaveLength(2);
    expect(screen.getByText('Conclusion')).toBeVisible();
  });

  it('keeps an unfinished disclosure and a fenced code example outside collapsible blocks', () => {
    const { container } = render(<LessonContent text={[
      '```md', ':::lesson-hint A marker shown in code', ':::end-lesson-disclosure', '```',
      '', ':::lesson-example Unfinished', 'Keep this text visible.',
    ].join('\n')} />);
    expect(container.querySelector('details')).toBeNull();
    expect(screen.getByText('Keep this text visible.', { exact: false })).toBeVisible();
  });

  it('embeds an explicit timed YouTube link with an optional caption preference', () => {
    render(<LessonContent text={'Video follows\n[Қазақша сабақ](https://www.youtube.com/watch?v=abcdefghijk&start=42&end=97&cc=kk)'} />);
    expect(screen.getByText('Video follows')).toBeInTheDocument();
    const frame = screen.getByTitle('Қазақша сабақ');
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute('src', 'https://www.youtube-nocookie.com/embed/abcdefghijk?start=42&end=97&playsinline=1&cc_lang_pref=kk&cc_load_policy=1');
  });

  it.each([
    'https://www.youtube.com.evil.test/watch?v=abcdefghijk&start=42&end=97',
    'https://www.youtube.com/watch?v=abcdefghijk&start=97&end=42',
    'https://www.youtube.com/watch?v=abcdefghijk&start=42&end=97&autoplay=1',
    'https://www.youtube.com/watch?v=abcdefghijk',
  ])('does not embed unrecognized links or invalid time ranges (%s)', (url) => {
    const { container } = render(<LessonContent text={`[Video](${url})`} />);
    expect(container.querySelector('iframe')).toBeNull();
  });

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
});
