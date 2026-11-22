import { lessonDisclosureRanges, nextMarkdownFence, readLessonDisclosure, type LessonDisclosure, type MarkdownFence } from './lessonDisclosure';
import { lessonTableAt, readLessonTable } from './lessonTable';

/** Lossless authoring segments. Markdown remains the only persisted content. */
export type LessonBlock = { markdown: string; after: string };
export type LessonBlockKind = 'text' | 'heading' | 'image' | 'rule' | 'steps' | 'table' | LessonDisclosure['kind'];

export function splitLessonBlocks(value: string): LessonBlock[] {
  if (!value) return [];
  const blocks: LessonBlock[] = [];
  const lines = value.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  let markdown = '';
  let after = '';
  const disclosures = lessonDisclosureRanges(value);
  let disclosureIndex = 0;
  let structuredEnd = 0;
  let structuredBlock = false;
  let offset = 0;
  let fence: MarkdownFence = null;
  for (const [index, line] of lines.entries()) {
    const start = offset;
    offset += line.length;
    if (start < structuredEnd) continue;
    const disclosure = disclosures[disclosureIndex];
    const hasDisclosure = disclosure?.start === start;
    if (!hasDisclosure) fence = nextMarkdownFence(line, fence);
    const table = !hasDisclosure && !fence && line.includes('|') && lessonTableAt(lines, index);
    if (hasDisclosure || table) {
      if (markdown || after) blocks.push({ markdown, after });
      if (hasDisclosure) {
        disclosureIndex += 1;
        structuredEnd = disclosure.end;
        markdown = value.slice(start, structuredEnd);
      } else if (table) {
        markdown = lines.slice(index, table.end).join('');
        structuredEnd = start + markdown.length;
      }
      structuredBlock = true;
      after = '';
      continue;
    }
    if (!fence && !line.trim() && markdown) {
      after += line;
      continue;
    }
    if (after || structuredBlock) {
      blocks.push({ markdown, after });
      markdown = ''; after = '';
      structuredBlock = false;
    }
    markdown += line;
  }
  if (markdown || after) blocks.push({ markdown, after });
  return blocks;
}

export function joinLessonBlocks(blocks: LessonBlock[]): string {
  return blocks.map(block => block.markdown + block.after).join('');
}

export function replaceLessonBlock(blocks: LessonBlock[], index: number, markdown: string): LessonBlock[] {
  return blocks.map((block, at) => {
    if (at !== index) return block;
    // The line terminator belongs to the paragraph boundary, not the edit field.
    const terminator = block.markdown.match(/\r?\n$/)?.[0] ?? '';
    return { ...block, markdown: markdown + (terminator && !markdown.endsWith('\n') ? terminator : '') };
  });
}

export function lessonBlockKind(markdown: string): LessonBlockKind {
  const disclosure = readLessonDisclosure(markdown);
  if (disclosure) return disclosure.kind;
  if (readLessonTable(markdown)) return 'table';
  const text = markdown.replace(/(?:\r?\n)+$/, '');
  if (/^#{1,6} [^\r\n]*$/.test(text)) return 'heading';
  if (/^!\[[^\r\n]*\]\([^\s()]+\)$/.test(text)) return 'image';
  const lines = text.split(/\r?\n/);
  if (lines.every(line => /^>/.test(line))) return 'rule';
  if (lines.every(line => /^\d+[.)]\s+/.test(line))) return 'steps';
  return 'text';
}

/** Structural operations add only the separator required between moved/new blocks. */
export function separateLessonBlocks(blocks: LessonBlock[]): LessonBlock[] {
  return blocks.map((block, index) => {
    if (index === blocks.length - 1 || /\n[ \t\r]*\n[ \t\r]*$/.test(block.markdown + block.after)) return block;
    const newline = (block.markdown + block.after).includes('\r\n') ? '\r\n' : '\n';
    return { ...block, after: block.after + ((block.markdown + block.after).endsWith('\n') ? newline : newline + newline) };
  });
}
