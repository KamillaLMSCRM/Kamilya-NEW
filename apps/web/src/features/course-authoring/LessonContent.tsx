import type { ReactNode } from 'react';

export type LessonContentProps = {
  text: string;
  className?: string;
};

type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

type Block =
  | { type: 'heading'; level: HeadingLevel; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'quote'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; rows: string[][] };

const headingPattern = /^(#{1,6})\s+(.+?)\s*$/;
const unorderedPattern = /^\s*[-+*]\s+(.+)$/;
const orderedPattern = /^\s*\d+[.)]\s+(.+)$/;

function splitTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes('|')) return null;

  const cells = trimmed
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());

  return cells.length > 1 ? cells : null;
}

function isTableDivider(line: string): boolean {
  const cells = splitTableRow(line);
  return Boolean(cells?.length && cells.every((cell) => /^:?-{3,}:?$/.test(cell)));
}

function startsBlock(lines: string[], index: number): boolean {
  const line = lines[index];
  return Boolean(
    line.match(headingPattern)
      || line.match(unorderedPattern)
      || line.match(orderedPattern)
      || /^\s*>/.test(line)
      || (splitTableRow(line) && index + 1 < lines.length && isTableDivider(lines[index + 1])),
  );
}

function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }

    const heading = lines[index].match(headingPattern);
    if (heading) {
      blocks.push({
        type: 'heading',
        level: heading[1].length as HeadingLevel,
        text: heading[2],
      });
      index += 1;
      continue;
    }

    const headerCells = splitTableRow(lines[index]);
    if (headerCells && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const rows = [headerCells];
      index += 2;

      while (index < lines.length && lines[index].trim()) {
        const row = splitTableRow(lines[index]);
        if (!row) break;

        rows.push(row);
        index += 1;
      }

      blocks.push({ type: 'table', rows });
      continue;
    }

    const firstUnordered = lines[index].match(unorderedPattern);
    const firstOrdered = lines[index].match(orderedPattern);
    if (firstUnordered || firstOrdered) {
      const ordered = Boolean(firstOrdered);
      const items: string[] = [];

      while (index < lines.length) {
        const match = lines[index].match(ordered ? orderedPattern : unorderedPattern);
        if (!match) break;

        items.push(match[1]);
        index += 1;
      }

      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    if (/^\s*>/.test(lines[index])) {
      const quoted: string[] = [];

      while (index < lines.length && /^\s*>/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*>\s?/, ''));
        index += 1;
      }

      blocks.push({ type: 'quote', text: quoted.join('\n') });
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !startsBlock(lines, index)) {
      paragraph.push(lines[index]);
      index += 1;
    }

    blocks.push({ type: 'paragraph', text: paragraph.join('\n') });
  }

  return blocks;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const tokenPattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_)/g;
  const output: ReactNode[] = [];
  let cursor = 0;
  let tokenIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(text))) {
    if (match.index > cursor) output.push(text.slice(cursor, match.index));

    const token = match[0];
    const strong = token.startsWith('**') || token.startsWith('__');
    const content = token.slice(strong ? 2 : 1, strong ? -2 : -1);
    const key = `${keyPrefix}-${tokenIndex}`;
    tokenIndex += 1;

    if (token.startsWith('`')) output.push(<code key={key}>{content}</code>);
    else if (strong) output.push(<strong key={key}>{content}</strong>);
    else output.push(<em key={key}>{content}</em>);

    cursor = match.index + token.length;
  }

  if (cursor < text.length || output.length === 0) output.push(text.slice(cursor));
  return output;
}

function renderMultilineInline(text: string, keyPrefix: string): ReactNode[] {
  return text.split('\n').flatMap((line, index) => [
    ...(index > 0 ? [<br key={`${keyPrefix}-br-${index}`} />] : []),
    ...renderInline(line, `${keyPrefix}-${index}`),
  ]);
}

function Heading({ level, children }: { level: HeadingLevel; children: ReactNode }) {
  switch (level) {
    case 1: return <h1>{children}</h1>;
    case 2: return <h2>{children}</h2>;
    case 3: return <h3>{children}</h3>;
    case 4: return <h4>{children}</h4>;
    case 5: return <h5>{children}</h5>;
    default: return <h6>{children}</h6>;
  }
}

export function LessonContent({ text, className }: LessonContentProps) {
  const blocks = parseBlocks(text);

  return (
    <div className={className}>
      {blocks.map((block, blockIndex) => {
        const key = `block-${blockIndex}`;

        if (block.type === 'heading') {
          return <Heading key={key} level={block.level}>{renderInline(block.text, key)}</Heading>;
        }

        if (block.type === 'paragraph') {
          return <p key={key}>{renderMultilineInline(block.text, key)}</p>;
        }

        if (block.type === 'quote') {
          return <blockquote key={key}>{renderMultilineInline(block.text, key)}</blockquote>;
        }

        if (block.type === 'list') {
          const List = block.ordered ? 'ol' : 'ul';
          return (
            <List key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
              ))}
            </List>
          );
        }

        return (
          <table key={key}>
            <thead>
              <tr>
                {block.rows[0].map((cell, cellIndex) => (
                  <th key={`${key}-heading-${cellIndex}`} scope="col">
                    {renderInline(cell, `${key}-heading-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.slice(1).map((row, rowIndex) => (
                <tr key={`${key}-row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${key}-${rowIndex}-${cellIndex}`}>
                      {renderInline(cell, `${key}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}
    </div>
  );
}
