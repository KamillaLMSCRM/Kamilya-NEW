import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SafeLessonContent } from '@/components/SafeLessonContent';

describe('SafeLessonContent', () => {
  it('renders generated headings, lists, tables, inline formatting, and plain text', () => {
    render(<SafeLessonContent text={'# Lesson section\n\nPlain **bold** and *emphasis*.\n\n- First\n- Second\n\n3. Three\n4. Four\n\n| Item | Value |\n| --- | --- |\n| Alpha | 42 |'} />);

    expect(screen.getByRole('heading', { level: 2, name: 'Lesson section' })).toBeInTheDocument();
    expect(screen.getByText('Plain', { exact: false }).closest('p')).toBeInTheDocument();
    expect(screen.getByText('bold').tagName).toBe('STRONG');
    expect(screen.getByText('emphasis').tagName).toBe('EM');
    const lists = screen.getAllByRole('list');
    expect(lists[0]).toHaveTextContent('FirstSecond');
    expect(lists[1]).toHaveAttribute('start', '3');
    expect(lists[1]).toHaveTextContent('ThreeFour');
    expect(screen.getByRole('table')).toHaveTextContent('ItemValueAlpha42');
    expect(screen.getByRole('heading')).toHaveClass('text-xl', 'font-semibold');
    expect(screen.getByRole('table').parentElement).toHaveClass('overflow-x-auto');
  });

  it('keeps HTML, unsafe URLs, and fenced code as inert text', () => {
    const { container } = render(<SafeLessonContent text={'<img src=x onerror=alert(1)> [bad](javascript:alert(1))\n\n```html\n<script>alert(1)</script>\n<iframe src="https://unsafe.example"></iframe>\n```'} />);

    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
    expect(screen.getByText(/javascript:alert/)).toBeInTheDocument();
    expect(screen.getByText(/<script>alert/)).toBeInTheDocument();
    expect(container.querySelectorAll('script, img, iframe, a')).toHaveLength(0);
  });

  it('preserves malformed tables, CRLF headings, unclosed fences, and long content without dropping it', () => {
    const longTail = `tail-${'x'.repeat(20_000)}`;
    render(<SafeLessonContent text={`## CRLF heading\r\n\r\n| Name | Value |\n| --- | --- |\n| Alpha | 1 | trailing |\n\n| Escaped \\| pipe | Value |\n| --- | --- |\n| Alpha | 1 |\n\n\`\`\`\nunclosed fence\n\n${longTail}`} />);

    expect(screen.getByRole('heading', { level: 3, name: 'CRLF heading' })).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('| Alpha | 1 | trailing |') === true)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent?.includes('| Escaped \\| pipe | Value |') === true)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'CODE' && element.textContent?.startsWith('```\nunclosed fence') === true)).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'CODE' && element.textContent?.includes(longTail) === true)).toBeInTheDocument();
  });
});
