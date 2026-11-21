export type LessonDisclosure = {
  kind: 'hint' | 'example';
  title: string;
  body: string;
};

type DisclosureRange = LessonDisclosure & { start: number; end: number };

const closingMarker = ':::end-lesson-disclosure';
const closingLine = /^:::end-lesson-disclosure[ \t]*$/;
const openingLine = /^:::lesson-(hint|example)(?: (.*))?$/;

function isControlLine(line: string): boolean {
  const marker = line.replace(/^\\+/, '').replace(/\r$/, '');
  return openingLine.test(marker) || closingLine.test(marker);
}

export type MarkdownFence = { char: string; length: number } | null;

export function nextMarkdownFence(line: string, fence: MarkdownFence): MarkdownFence {
  const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$/);
  if (!marker) return fence;
  if (!fence) return { char: marker[1][0], length: marker[1].length };
  return marker[1][0] === fence.char && marker[1].length >= fence.length && !marker[2].trim()
    ? null : fence;
}

export function lessonDisclosureRanges(text: string): DisclosureRange[] {
  const ranges: DisclosureRange[] = [];
  let current: Omit<DisclosureRange, 'body' | 'end'> & { bodyStart: number } | undefined;
  let fence: MarkdownFence = null;
  let offset = 0;
  for (const raw of text.match(/[^\n]*\n|[^\n]+$/g) ?? []) {
    const start = offset;
    offset += raw.length;
    const line = raw.replace(/\r?\n$/, '');
    if (current) {
      if (closingLine.test(line)) {
        const body = text.slice(current.bodyStart, start).replace(/\r?\n$/, '')
          .split('\n').map(value => value.startsWith('\\') && isControlLine(value) ? value.slice(1) : value).join('\n');
        ranges.push({ kind: current.kind, title: current.title, start: current.start, end: offset, body });
        current = undefined;
      }
      if (!openingLine.test(line)) continue;
    }

    fence = nextMarkdownFence(line, fence);
    const opening = !fence && line.match(openingLine);
    if (opening) {
      current = { kind: opening[1] === 'hint' ? 'hint' : 'example', title: opening[2] ?? '', start, bodyStart: offset };
    }
  }
  return ranges;
}

export function readLessonDisclosure(markdown: string): LessonDisclosure | undefined {
  const [range] = lessonDisclosureRanges(markdown);
  if (range?.start !== 0 || range.end !== markdown.length) return undefined;
  return { kind: range.kind, title: range.title, body: range.body };
}

export function writeLessonDisclosure({ kind, title, body }: LessonDisclosure): string {
  const escaped = body.split('\n').map(line => isControlLine(line) ? '\\' + line : line).join('\n');
  return `:::lesson-${kind} ${title.replace(/[\r\n]+/g, ' ')}\n${escaped}\n${closingMarker}`;
}
