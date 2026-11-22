import { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { VisualLessonEditor } from '@/features/course-authoring/VisualLessonEditor';
import { joinLessonBlocks, lessonBlockKind, replaceLessonBlock, separateLessonBlocks, splitLessonBlocks } from '@/features/course-authoring/lessonBlocks';
import { readLessonDisclosure, writeLessonDisclosure } from '@/features/course-authoring/lessonDisclosure';
import { readLessonTable, tableCellMarkdown, tableCellText } from '@/features/course-authoring/lessonTable';
import { visualLessonCopy } from '@/features/course-authoring/visualLessonCopy';
import { sourceImageLine } from '@/components/AuthenticatedSourceImage';

vi.mock('@/lib/api', () => ({ api: { post: vi.fn(), get: vi.fn().mockRejectedValue(new Error('No image transport in this component test')) } }));

const asset = '/v1/courses/00000000-0000-4000-8000-000000000001/lessons/00000000-0000-4000-8000-000000000002/source-assets/asset-' + 'a'.repeat(64);
describe('lossless lesson authoring', () => {
  it('keeps an adjacent legacy table separate without rewriting its CRLF bytes', () => {
    const value = 'Before\r\nA | B\r\n:--- | ---:\r\nOne | Two\r\nAfter';
    const blocks = splitLessonBlocks(value);
    expect(blocks.map(block => lessonBlockKind(block.markdown))).toEqual(['text', 'table', 'text']);
    expect(joinLessonBlocks(blocks)).toBe(value);
    expect(readLessonTable(blocks[1].markdown)?.dividers).toEqual([':---', '---:']);
  });

  it('leaves table syntax in a code fence in the text block', () => {
    const value = '```md\n| A | B |\n| --- | --- |\n| One | Two |\n```\n\nAfter';
    const blocks = splitLessonBlocks(value);
    expect(blocks.map(block => lessonBlockKind(block.markdown))).toEqual(['text', 'text']);
    expect(joinLessonBlocks(blocks)).toBe(value);
  });

  it('round trips literal pipes and backslashes in a cell', () => {
    const raw = 'A | B \\| C \\\\| D';
    const cell = tableCellMarkdown(raw);
    const table = readLessonTable(`| A |\n| --- |\n| ${cell} |`);
    expect(table?.rows[1]).toEqual([cell]);
    expect(tableCellText(cell)).toBe(raw);
  });
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
  it('round trips a multiline disclosure, fenced Markdown and an unfinished disclosure', () => {
    const value = 'First\r\n:::lesson-hint Read the panel\r\nOne\r\n\r\nTwo\r\n:::end-lesson-disclosure\r\nNext'
      + '\r\n\r\n```text\r\n:::lesson-example Code only\r\n:::end-lesson-disclosure\r\n```'
      + '\r\n\r\n:::lesson-example Missing close';
    const blocks = splitLessonBlocks(value);
    expect(blocks.map(block => lessonBlockKind(block.markdown))).toEqual(['text', 'hint', 'text', 'text', 'text']);
    expect(readLessonDisclosure(blocks[1].markdown)?.body).toBe('One\r\n\r\nTwo');
    expect(joinLessonBlocks(blocks)).toBe(value);
  });
  it('retains reserved marker lines typed as disclosure content', () => {
    const disclosure = { kind: 'example', title: 'Markers', body: 'Before\n:::end-lesson-disclosure\n\\:::lesson-hint Inside\n\nAfter\n' } as const;
    expect(readLessonDisclosure(writeLessonDisclosure(disclosure))).toEqual(disclosure);
  });
  it('does not merge an unterminated last paragraph into its new neighbor', () => {
    const blocks = splitLessonBlocks('First\r\n\r\nLast');
    expect(joinLessonBlocks(separateLessonBlocks([blocks[1], blocks[0]]))).toBe('Last\n\nFirst\r\n\r\n');
  });
});

function Harness({ initial = '# Title\n\nBody', disabled = false, illustrationEndpoint }: { initial?: string; disabled?: boolean; illustrationEndpoint?: string }) {
  const [value, setValue] = useState(initial);
  return <><VisualLessonEditor value={value} onChange={setValue} lang="en" disabled={disabled} illustrationEndpoint={illustrationEndpoint} /><output aria-label="Saved draft">{value}</output></>;
}
describe('uploaded lesson illustrations', () => {
  const url = asset.replace(/asset-a+$/, 'illustration-' + 'a'.repeat(64) + '.png');
  const endpoint = url.slice(0, url.indexOf('/source-assets/')) + '/illustrations';

  it('uploads a binary file and edits separate caption and alternative text', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { url } });
    render(<Harness illustrationEndpoint={endpoint} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add block' }));
    const file = new File(['fake image'], 'diagram.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Upload illustration', { selector: 'input' }), { target: { files: [file] } });
    await screen.findByRole('textbox', { name: 'Image description' });
    fireEvent.change(screen.getByRole('textbox', { name: 'Image description' }), { target: { value: 'Screen [A]' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Caption' }), { target: { value: 'Point "A" ](/v1/example)' } });
    const block = splitLessonBlocks(screen.getByLabelText('Saved draft').textContent!).at(-1)!;
    expect(sourceImageLine(block.markdown)).toEqual({ alt: 'Screen [A]', url, caption: 'Point "A" ](/v1/example)' });
    const [sentTo, payload] = vi.mocked(api.post).mock.calls.at(-1)!;
    expect(sentTo).toBe(endpoint);
    expect((payload as FormData).get('file')).toEqual(file);
  });

  it('keeps current blocks when the upload fails', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('failed'));
    render(<Harness illustrationEndpoint={endpoint} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add block' }));
    fireEvent.change(screen.getByLabelText('Upload illustration', { selector: 'input' }), {
      target: { files: [new File(['data'], 'diagram.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Could not upload'));
    expect(screen.getByLabelText('Saved draft').textContent).toBe('# Title\n\nBody');
  });
});

describe('visual lesson editor behavior', () => {
  it('creates a table and edits, adds and deletes rows and columns', () => {
    render(<Harness initial="Before" />);
    fireEvent.click(screen.getByRole('button', { name: 'Add block' }));
    fireEvent.click(screen.getByRole('button', { name: 'Table' }));
    const first = screen.getByRole('textbox', { name: 'Header 1' });
    fireEvent.change(first, { target: { value: 'If ' } });
    expect(first).toHaveValue('If ');
    fireEvent.change(first, { target: { value: 'If needed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add column' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add row' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Cell 2, 3' }), { target: { value: 'A | B' } });
    fireEvent.click(screen.getByRole('button', { name: 'Delete row 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete column 2' }));
    expect(screen.getByRole('textbox', { name: 'Cell 1, 2' })).toHaveValue('A | B');
    fireEvent.click(screen.getByRole('button', { name: 'Delete column 1' }));
    expect(screen.getByRole('button', { name: 'Delete column 1' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete row 1' }));
    expect(screen.getByLabelText('Saved draft').textContent).toBe('Before\n\n|  |\n| --- |');
  });

  it('opens a legacy table without writing and preserves neighbouring content after editing', () => {
    const initial = 'Intro\r\nA | B\r\n:--- | ---:\r\nOne | **Two**\r\nOutro';
    render(<Harness initial={initial} />);
    fireEvent.click(screen.getByRole('button', { name: '2. Table' }));
    expect(screen.getByLabelText('Saved draft').textContent).toBe(initial);
    fireEvent.change(screen.getByRole('textbox', { name: 'Cell 1, 1' }), { target: { value: 'Changed' } });
    expect(screen.getByLabelText('Saved draft').textContent).toBe(
      'Intro\r\n| A | B |\r\n| :--- | ---: |\r\n| Changed | **Two** |\r\nOutro',
    );
  });
  it.each(['Hint', 'Example'] as const)('adds and edits a %s with its own title and body', (label) => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Add block' }));
    fireEvent.click(screen.getByRole('button', { name: label }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Block title' }), { target: { value: 'Check before starting' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Block content' }), { target: { value: 'First line\n\nSecond line' } });
    const saved = screen.getByLabelText('Saved draft').textContent!;
    const blocks = splitLessonBlocks(saved);
    expect(blocks).toHaveLength(3);
    expect(blocks.slice(0, 2).map(block => block.markdown.trim())).toEqual(['# Title', 'Body']);
    expect(readLessonDisclosure(blocks[2].markdown)).toEqual({
      kind: label.toLowerCase(), title: 'Check before starting', body: 'First line\n\nSecond line',
    });
    expect(screen.getByText('Check before starting', { selector: 'summary' })).toBeVisible();
  });
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
