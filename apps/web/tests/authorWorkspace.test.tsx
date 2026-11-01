import { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { formatMarkdown, MarkdownToolbar } from '@/features/course-authoring/MarkdownToolbar';
import { CourseReadiness } from '@/features/course-authoring/CourseReadiness';
import { authorWorkspaceCopy } from '@/features/course-authoring/authorWorkspaceCopy';

describe('author workspace canonical text controls', () => {
  it.each([
    ['bold', '**alpha**'], ['italic', '*alpha*'], ['code', '`alpha`'],
    ['heading', '## alpha'], ['bullets', '- alpha'], ['numbered', '1. alpha'], ['quote', '> alpha'],
  ] as const)('applies %s without converting to HTML', (format, expected) => {
    expect(formatMarkdown('alpha', 0, 5, format, 'text').value).toBe(expected);
  });

  it('prefixes whole selected lines and leaves following text and CRLF intact', () => {
    expect(formatMarkdown('first\r\nsecond\r\nthird', 0, 15, 'numbered', 'text').value).toBe('1. first\r\n2. second\r\nthird');
  });

  it('formats multiline selections using the existing line-local rendering contract', () => {
    const source = 'first\r\n\r\nsecond';
    expect(formatMarkdown(source, 0, source.length, 'bold', 'text').value).toBe('**first**\r\n\r\n**second**');
    expect(formatMarkdown('\nsecond', 0, 0, 'heading', 'text').value).toBe('## \nsecond');
  });

  it('inserts an editable localized placeholder without replacing neighboring text', () => {
    expect(formatMarkdown('left right', 5, 5, 'bold', 'text')).toEqual({ value: 'left **text**right', start: 7, end: 11 });
  });

  it('supports toolbar keyboard traversal and returns selection to the text editor', () => {
    function Harness() {
      const ref = useRef<HTMLTextAreaElement>(null);
      const [value, setValue] = useState('alpha');
      return <><MarkdownToolbar lang="en" value={value} onChange={setValue} textareaRef={ref} /><textarea aria-label="Body" ref={ref} value={value} onChange={(event) => setValue(event.target.value)} /></>;
    }
    render(<Harness />);
    const first = screen.getByRole('button', { name: 'Bold' }); first.focus();
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(screen.getByRole('button', { name: 'Italic' })).toHaveFocus();
    const textarea = screen.getByRole('textbox', { name: 'Body' }) as HTMLTextAreaElement;
    textarea.setSelectionRange(0, 5); fireEvent.click(first);
    expect(textarea).toHaveValue('**alpha**'); expect(textarea).toHaveFocus();
    expect([textarea.selectionStart, textarea.selectionEnd]).toEqual([2, 7]);
  });
});

describe('factual author readiness', () => {
  it('reports counts and review status without asserting semantic completeness', () => {
    render(<CourseReadiness lang="en" moduleCount={2} lessonCount={4} dirty={false} requiresReview reviewStatus="approved" unavailable={false} />);
    expect(screen.getByText('Modules: 2 · Lessons: 4')).toBeInTheDocument();
    expect(screen.getByText('Approved')).toBeInTheDocument();
    expect(screen.getByText(/not an assessment of meaning/)).toBeInTheDocument();
    expect(screen.queryByText(/100%|ready to publish/i)).not.toBeInTheDocument();
  });

  it('does not keep an approval claim when the saved-version readback is unavailable', () => {
    render(<CourseReadiness lang="en" moduleCount={2} lessonCount={4} dirty requiresReview reviewStatus="approved" unavailable />);
    expect(screen.queryByText('Approved')).not.toBeInTheDocument();
    expect(screen.getByText(/Save or discard/)).toBeInTheDocument();
  });

  it.each(['ru', 'kk', 'en'])('owns complete %s copy without changing shared locale files', (lang) => {
    const copy = authorWorkspaceCopy(lang);
    expect(Object.values(copy).every((value) => value.length > 0)).toBe(true);
    expect(copy.readiness).not.toBe(copy.questionDirty);
  });
});
