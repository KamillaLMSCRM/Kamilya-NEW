import { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VisualLessonEditor } from '@/features/course-authoring/VisualLessonEditor';
import { joinLessonBlocks, replaceLessonBlock, separateLessonBlocks, splitLessonBlocks } from '@/features/course-authoring/lessonBlocks';
import { visualLessonCopy } from '@/features/course-authoring/visualLessonCopy';
import { sourceImageLine } from '@/components/AuthenticatedSourceImage';

vi.mock('@/lib/api', () => ({ api: { get: vi.fn().mockRejectedValue(new Error('No image transport in this component test')) } }));

const asset = '/v1/courses/00000000-0000-4000-8000-000000000001/lessons/00000000-0000-4000-8000-000000000002/source-assets/asset-' + 'a'.repeat(64);
describe('lossless lesson authoring', () => {
  it.each(['', '\n\n', 'plain', '# Title\r\n\r\nBody\r\n\r\n',
    '| A | B |\n| --- | --- |\n| x | y |\n\n> Keep\n> this\n',
    '2) Second\r\n10. Tenth\r\n\r\n!\u005bCaption\u005d(' + asset + ')\r\n',
    '~~~text\nalpha\n\nbeta\n~~~\n\nlast', '```md\n\n# Inside\n\n```\n\nafter',
    '<unknown data-preserve="yes">\r\n\r\nNo parsing loss\r\n</unknown>'])('round trips %j exactly', value => {
    expect(joinLessonBlocks(splitLessonBlocks(value))).toBe(value);
  });
  it('keeps a fenced code block together and changes only a chosen neighbor', () => {
    const value = 'Before\n\n```text\nx\n\ny\n```\n\nAfter\r\n';
    const blocks = splitLessonBlocks(value);
    expect(blocks).toHaveLength(3);
    blocks[2] = { ...blocks[2], markdown: 'Changed\r\n' };
    expect(joinLessonBlocks(blocks)).toBe(value.replace('After', 'Changed'));
  });
  it('retains paragraph boundaries and CRLF when the edited text omits its final newline', () => {
    const blocks = splitLessonBlocks('First\r\n\r\nSecond\r\n\r\nLast');
    expect(joinLessonBlocks(replaceLessonBlock(blocks, 0, 'Changed'))).toBe('Changed\r\n\r\nSecond\r\n\r\nLast');
    expect(replaceLessonBlock(blocks, 0, 'Changed').slice(1)).toEqual(blocks.slice(1));
  });
  it('does not merge an unterminated last paragraph into its new neighbor', () => {
    const blocks = splitLessonBlocks('First\r\n\r\nLast');
    expect(joinLessonBlocks(separateLessonBlocks([blocks[1], blocks[0]]))).toBe('Last\n\nFirst\r\n\r\n');
  });
});

function Harness({ initial = '# Title\n\nBody', disabled = false }: { initial?: string; disabled?: boolean }) {
  const [value, setValue] = useState(initial);
  return <><VisualLessonEditor value={value} onChange={setValue} lang="en" disabled={disabled} /><output aria-label="Saved draft">{value}</output></>;
}
describe('visual lesson editor behavior', () => {
  it('opens and selects existing blocks without emitting a write', () => {
    const onChange = vi.fn();
    render(<VisualLessonEditor value={'## Existing\r\n\r\nBody'} onChange={onChange} lang="en" />);
    fireEvent.click(screen.getByRole('button', { name: '1. Heading' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onChange).not.toHaveBeenCalled();
  });
  it('edits only the selected block and can cancel or confirm removal', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '2. Text' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Block content: 2' }), { target: { value: 'Improved body' } });
    expect(screen.getByLabelText('Saved draft')).toHaveTextContent('# Title Improved body');
    fireEvent.click(screen.getByRole('button', { name: 'Delete block: 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete block: 1' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Delete this block?' })).getByRole('button', { name: 'Delete block' }));
    expect(screen.queryByRole('heading', { name: 'Title' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Saved draft').textContent).toBe('Improved body');
  });
  it('adds a block after selection, moves it with keyboard controls and renders through the shared player', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '1. Heading' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add block' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Add block' })).getByRole('button', { name: 'Process steps' }));
    expect(screen.getByRole('list')).toHaveTextContent('First stepSecond step');
    fireEvent.click(screen.getByRole('button', { name: 'Move down: 2' }));
    expect(screen.getByRole('button', { name: '3. Process steps' })).toHaveFocus();
    expect(screen.getByLabelText('Saved draft').textContent).toBe('# Title\n\nBody\n\n1. First step\n2. Second step\n\n');
  });
  it('does not retain selected block or pending delete when parent content changes', () => {
    const { rerender } = render(<VisualLessonEditor value="old" onChange={vi.fn()} lang="en" />);
    fireEvent.click(screen.getByRole('button', { name: '1. Text' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete block: 1' }));
    rerender(<VisualLessonEditor value="replacement" onChange={vi.fn()} lang="en" />);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Delete this block?' })).not.toBeInTheDocument();
    expect(screen.getByText('replacement')).toBeInTheDocument();
  });
  it('edits heading, rule and step fields without requiring Markdown markers or renumbering source ordinals', () => {
    render(<Harness initial={'### Heading\r\n\r\n> Rule\r\n\r\n2) Step two\r\n10. Step ten'} />);
    fireEvent.click(screen.getByRole('button', { name: '1. Heading' }));
    expect(screen.getByRole('textbox', { name: 'Block content: 1' })).toHaveValue('Heading');
    fireEvent.change(screen.getByRole('textbox', { name: 'Block content: 1' }), { target: { value: 'Changed' } });
    fireEvent.click(screen.getByRole('button', { name: '2. Key rule' }));
    expect(screen.getByRole('textbox', { name: 'Block content: 2' })).toHaveValue('Rule');
    fireEvent.change(screen.getByRole('textbox', { name: 'Block content: 2' }), { target: { value: 'Do this\nThen that' } });
    fireEvent.click(screen.getByRole('button', { name: '3. Process steps' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Process steps: 2' }), { target: { value: 'Changed ten' } });
    expect(screen.getByLabelText('Saved draft').textContent).toBe('### Changed\r\n\r\n> Do this\n> Then that\r\n\r\n2) Step two\r\n10. Changed ten');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });
  it('disables editing, movement, insertion and deletion while its owner is busy', () => {
    render(<Harness disabled />);
    screen.getAllByRole('button').forEach(button => expect(button).toBeDisabled());
  });
  it('chooses among existing source images and edits a bracketed caption without changing the protected URL', () => {
    const second = asset.replace(/a{64}$/, 'b'.repeat(64));
    render(<Harness initial={`![First](${asset})\n\n![Second](${second})`} />);
    fireEvent.click(screen.getByRole('button', { name: '2. Source illustration' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Illustration' }), { target: { value: asset } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Caption' }), { target: { value: 'Field [A] \\ example' } });
    expect(sourceImageLine(splitLessonBlocks(screen.getByLabelText('Saved draft').textContent!)[1].markdown)).toEqual({ alt: 'Field [A] \\ example', url: asset });
    expect(screen.getByRole('combobox', { name: 'Illustration' }).querySelectorAll('option')).toHaveLength(2);
    expect(screen.queryByRole('textbox', { name: /URL/ })).not.toBeInTheDocument();
  });
  it('keeps heading and step controls mounted while a field is cleared and retyped', () => {
    render(<Harness initial={'## Title\n\n1. One\n2. Two'} />);
    fireEvent.click(screen.getByRole('button', { name: '1. Heading' }));
    const heading = screen.getByRole('textbox', { name: 'Block content: 1' });
    fireEvent.change(heading, { target: { value: '' } });
    expect(screen.getByRole('textbox', { name: 'Block content: 1' })).toBe(heading);
    expect(heading.tagName).toBe('INPUT'); expect(heading).toHaveValue('');
    fireEvent.change(heading, { target: { value: 'New title' } });
    fireEvent.click(screen.getByRole('button', { name: '2. Process steps' }));
    const second = screen.getByRole('textbox', { name: 'Process steps: 2' });
    fireEvent.change(second, { target: { value: '' } });
    expect(screen.getByRole('textbox', { name: 'Process steps: 2' })).toBe(second);
    fireEvent.change(second, { target: { value: 'New second' } });
    expect(screen.getByLabelText('Saved draft').textContent).toBe('## New title\n\n1. One\n2. New second');
  });
  it.each(['ru', 'kk', 'en'])('has nonempty %s labels', lang => {
    expect(Object.values(visualLessonCopy(lang)).every(Boolean)).toBe(true);
  });
});
