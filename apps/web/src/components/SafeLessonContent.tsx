import { Fragment, type ReactNode } from 'react';

type SafeLessonContentProps = {
  text: string;
};

const headingPattern = /^(#{1,6})\s+(.+)$/;
const unorderedListPattern = /^[-*+]\s+(.+)$/;
const orderedListPattern = /^(\d+)[.)]\s+(.+)$/;

function inlineContent(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g).map((segment, index) => {
    const key = `${keyPrefix}:${index}`;
    if (segment.startsWith('**') && segment.endsWith('**')) {
      return <strong key={key}>{segment.slice(2, -2)}</strong>;
    }
    if (segment.startsWith('*') && segment.endsWith('*')) {
      return <em key={key}>{segment.slice(1, -1)}</em>;
    }
    return <Fragment key={key}>{segment}</Fragment>;
  });
}

function tableCells(line: string): string[] {
  const trimmed = line.trim();
  return (trimmed.startsWith('|') ? trimmed.slice(1) : trimmed)
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isTableSeparator(line: string): boolean {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isTableStart(lines: string[], index: number): boolean {
  return lines[index].includes('|') && index + 1 < lines.length && isTableSeparator(lines[index + 1]);
}

function literalLines(lines: string[], keyPrefix: string): ReactNode[] {
  return lines.map((line, index) => (
    <Fragment key={`${keyPrefix}:${index}`}>
      {line}
      {index < lines.length - 1 && <br />}
    </Fragment>
 ));
}

export function SafeLessonContent({ text }: SafeLessonContentProps) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === '') {
      index += 1;
      continue;
    }

    if (line.trimStart().startsWith('```')) {
      const codeLines: string[] = [];
      const openingFence = line;
      index += 1;
      while (index < lines.length && !lines[index].trimStart().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      const isClosed = index < lines.length;
      if (isClosed) index += 1;
      if (!isClosed) codeLines.unshift(openingFence);
      blocks.push(<pre key={`code:${blocks.length}`} className="overflow-x-auto rounded-md bg-muted p-3 text-sm"><code>{codeLines.join('\n')}</code></pre>);
      continue;
    }

    const heading = line.match(headingPattern);
    if (heading) {
      const Heading = `h${Math.min(6, heading[1].length + 1)}` as keyof JSX.IntrinsicElements;
      blocks.push(<Heading key={`heading:${blocks.length}`} className="mt-6 text-xl font-semibold first:mt-0">{inlineContent(heading[2], `heading:${index}`)}</Heading>);
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const tableLines = [line, lines[index + 1]];
      let tableEnd = index + 2;
      while (tableEnd < lines.length && lines[tableEnd].includes('|') && lines[tableEnd].trim() !== '') {
        tableLines.push(lines[tableEnd]);
        tableEnd += 1;
      }
      index = tableEnd;
      const cells = tableLines.map(tableCells);
      const headers = cells[0];
      const hasUnsupportedEscape = tableLines.some((tableLine) => tableLine.includes('\\|'));
      const hasMatchingWidths = cells.every((row) => row.length === headers.length);
      if (hasUnsupportedEscape || !hasMatchingWidths) {
        blocks.push(<p key={`malformed-table:${blocks.length}`} className="whitespace-pre-wrap">{literalLines(tableLines, `malformed-table:${index}`)}</p>);
        continue;
      }
      const rows = cells.slice(2);
      blocks.push(
        <div key={`table:${blocks.length}`} className="overflow-x-auto">
          <table className="min-w-full border-collapse border border-border text-left">
            <thead><tr>{headers.map((header, cellIndex) => <th key={cellIndex} className="border border-border bg-muted px-3 py-2 font-semibold">{inlineContent(header, `header:${cellIndex}`)}</th>)}</tr></thead>
            <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex} className="border border-border px-3 py-2">{inlineContent(cell, `cell:${rowIndex}:${cellIndex}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }

    const unordered = line.match(unorderedListPattern);
    const ordered = line.match(orderedListPattern);
    if (unordered || ordered) {
      const pattern = unordered ? unorderedListPattern : orderedListPattern;
      const items: Array<{ number?: number; text: string }> = [];
      while (index < lines.length) {
        const match = lines[index].match(pattern);
        if (!match) break;
        items.push(unordered ? { text: match[1] } : { number: Number(match[1]), text: match[2] });
        index += 1;
      }
      const List = unordered ? 'ul' : 'ol';
      blocks.push(<List key={`list:${blocks.length}`} className={unordered ? 'list-disc space-y-1 pl-6' : 'list-decimal space-y-1 pl-6'} start={unordered ? undefined : items[0].number}>{items.map((item, itemIndex) => <li key={itemIndex} value={item.number}>{inlineContent(item.text, `list:${index}:${itemIndex}`)}</li>)}</List>);
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() !== '' && !lines[index].trimStart().startsWith('```') && !headingPattern.test(lines[index]) && !isTableStart(lines, index) && !unorderedListPattern.test(lines[index]) && !orderedListPattern.test(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph:${blocks.length}`} className="whitespace-pre-wrap">
        {paragraph.map((paragraphLine, lineIndex) => (
          <Fragment key={lineIndex}>
            {inlineContent(paragraphLine, `paragraph:${index}:${lineIndex}`)}
            {lineIndex < paragraph.length - 1 && <br />}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="space-y-4 leading-7">{blocks}</div>;
}
