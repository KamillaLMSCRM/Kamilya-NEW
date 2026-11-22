import { nextMarkdownFence } from './lessonDisclosure';

export type LessonTable = { rows: string[][]; dividers: string[] };

function splitTableRow(line: string): string[] | null {
  const text = line.trim();
  const cells: string[] = [];
  let start = 0;
  for (const match of text.matchAll(/\\*\|/g)) {
    const backslashes = match[0].length - 1;
    if (backslashes % 2 !== 0) continue;
    const delimiter = match.index + backslashes;
    cells.push(text.slice(start, delimiter));
    start = delimiter + 1;
  }
  if (!cells.length) return null;
  cells.push(text.slice(start));
  const leading = text.startsWith('|');
  const trailing = start === text.length;
  if (leading) cells.shift();
  if (trailing) cells.pop();
  if (cells.length < 2 && !(cells.length === 1 && leading && trailing)) return null;
  return cells.map(cell => cell.replace(/^[ \t]/, '').replace(/[ \t]$/, ''));
}

export function tableCellText(markdown: string): string {
  return markdown.replace(/(\\+)\|/g, (_, slashes: string) => '\\'.repeat((slashes.length - 1) / 2) + '|');
}

export function tableCellMarkdown(text: string): string {
  return text.replace(/(\\*)\|/g, (_, slashes: string) => '\\'.repeat(slashes.length * 2 + 1) + '|');
}

function tableOpening(lines: string[], start: number): LessonTable | undefined {
  const header = splitTableRow(lines[start] ?? '');
  const dividers = header && splitTableRow(lines[start + 1] ?? '')?.map(cell => cell.trim());
  if (!header || !dividers?.every(cell => /^:?-{3,}:?$/.test(cell))) return undefined;
  return { rows: [header], dividers };
}

export function startsLessonTable(lines: string[], index: number): boolean {
  return Boolean(tableOpening(lines, index));
}

export function lessonTableAt(lines: string[], start: number): (LessonTable & { end: number }) | undefined {
  const table = tableOpening(lines, start);
  if (!table) return undefined;
  let end = start + 2;
  while (end < lines.length) {
    const line = lines[end];
    if (nextMarkdownFence(line, null) || /^:::lesson-(?:hint|example)(?: |\s*$)/.test(line)) break;
    const row = splitTableRow(line);
    if (!row) break;
    table.rows.push(row);
    end += 1;
  }
  return { ...table, end };
}

export function readLessonTable(markdown: string): LessonTable | undefined {
  const lines = markdown.replace(/\r?\n$/, '').split(/\r?\n/);
  const table = lessonTableAt(lines, 0);
  return table?.end === lines.length ? table : undefined;
}

export function writeLessonTable({ rows, dividers }: LessonTable, newline = '\n'): string {
  return [rows[0], dividers, ...rows.slice(1)].map(row => '| ' + row.join(' | ') + ' |').join(newline);
}
