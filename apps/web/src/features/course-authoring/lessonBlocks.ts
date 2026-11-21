import { lessonDisclosureRanges, nextMarkdownFence, readLessonDisclosure, type LessonDisclosure, type MarkdownFence } from './lessonDisclosure';

/** Lossless authoring segments. Markdown remains the only persisted content. */
export type LessonBlock = { markdown: string; after: string };
export type LessonBlockKind = 'text' | 'heading' | 'image' | 'rule' | 'steps' | LessonDisclosure['kind'];

export function splitLessonBlocks(value: string): LessonBlock[] {
  if (!value) return [];
  const blocks: LessonBlock[] = [];
  const lines = value.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  let markdown = '';
  let after = '';
  const disclosures = lessonDisclosureRanges(value);
  let disclosureIndex = 0;
  let disclosureEnd = 0;
  let disclosureBlock = false;
  let offset = 0;
  let fence: MarkdownFence = null;
  for (const line of lines) {
    const start = offset;
    offset += line.length;
    if (start < disclosureEnd) continue;
    const disclosure = disclosures[disclosureIndex];
    if (disclosure?.start === start) {
      if (markdown || after) blocks.push({ markdown, after });
      disclosureIndex += 1;
      disclosureEnd = disclosure.end;
      disclosureBlock = true;
      markdown = value.slice(start, disclosureEnd);
      after = '';
      continue;
    }
    fence = nextMarkdownFence(line, fence);
    if (!fence && !line.trim() && markdown) {
      after += line;
      continue;
    }
    if (after || disclosureBlock) {
      blocks.push({ markdown, after });
      markdown = ''; after = '';
      disclosureBlock = false;
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
