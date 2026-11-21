'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { AuthenticatedSourceImage, sourceImageLine } from '@/components/AuthenticatedSourceImage';
import { api } from '@/lib/api';
import { useLanguageStore } from '@/store/languageStore';
import { type CourseLanguage } from './courseLanguages';
import { lessonDisclosureRanges, type LessonDisclosure } from './lessonDisclosure';
import { TimedPracticeVideo } from './TimedPracticeVideo';
import { youtubeFrameProps } from './useYoutubeTiming';
import { practiceMatches, practicePath, type VideoClip, type VideoPractice } from './videoPractice';
import { visualLessonCopy } from './visualLessonCopy';

export const lessonContentClassName = 'space-y-5 text-base leading-7 text-foreground [&_blockquote]:border-l-4 [&_blockquote]:border-primary/40 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_h1]:text-3xl [&_h1]:font-bold [&_h2]:mt-8 [&_h2]:text-2xl [&_h2]:font-semibold [&_h3]:mt-6 [&_h3]:text-xl [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:p-2 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-2 [&_th]:text-left [&_ul]:list-disc';

export type LessonContentProps = {
  text: string;
  className?: string;
  omitFirstHeading?: string;
  practiceScope?: { courseId: string; lessonId: string; language: CourseLanguage };
};

type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;
type ListItem = { text: string; value?: number };

type Block =
  | { type: 'heading'; level: HeadingLevel; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'quote'; text: string }
  | { type: 'image'; alt: string; url: string; caption?: string }
  | { type: 'youtube'; title: string; src: string }
  | { type: 'list'; ordered: boolean; items: ListItem[] }
  | { type: 'table'; rows: string[][] };
type RenderBlock = Block | (LessonDisclosure & { type: 'disclosure' });

const headingPattern = /^(#{1,6})\s+(.+?)\s*$/;
const unorderedPattern = /^\s*[-+*]\s+(.+)$/;
const orderedPattern = /^\s*(\d+)[.)]\s+(.+)$/;

function youtubeVideoLine(line: string): Extract<Block, { type: 'youtube' }> | null {
  // An explicit timed link opts into embedding. Ordinary links and raw HTML stay inert.
  const match = line.trim().match(/^\[([^\]]+)\]\(https:\/\/www\.youtube\.com\/watch\?v=([\w-]{11})&start=(\d+)&end=(\d+)(?:&cc=(kk|ru|en))?\)$/);
  if (!match) return null;
  const [, title, id, begin, finish, language] = match;
  const start = Number(begin);
  const end = Number(finish);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || end <= start) return null;
  const src = new URL(`https://www.youtube-nocookie.com/embed/${id}`);
  src.searchParams.set('start', String(start));
  src.searchParams.set('end', String(end));
  src.searchParams.set('playsinline', '1');
  if (language) {
    src.searchParams.set('cc_lang_pref', language);
    src.searchParams.set('cc_load_policy', '1');
  }
  return { type: 'youtube', title, src: src.href };
}

export const containsTimedVideo = (text: string) => text.split('\n').some(line => youtubeVideoLine(line) !== null);

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
      || sourceImageLine(line)
      || youtubeVideoLine(line)
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

    const image = sourceImageLine(lines[index]);
    if (image) { blocks.push({ type: 'image', ...image }); index += 1; continue; }
    const youtube = youtubeVideoLine(lines[index]);
    if (youtube) { blocks.push(youtube); index += 1; continue; }

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
      const items: ListItem[] = [];

      while (index < lines.length) {
        const match = lines[index].match(ordered ? orderedPattern : unorderedPattern);
        if (!match) break;

        items.push(ordered
          ? { text: match[2], value: Number(match[1]) }
          : { text: match[1] });
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

function parseLesson(text: string): RenderBlock[] {
  const blocks: RenderBlock[] = [];
  let cursor = 0;
  for (const { start, end, kind, title, body } of lessonDisclosureRanges(text)) {
    blocks.push(...parseBlocks(text.slice(cursor, start)), { type: 'disclosure', kind, title, body });
    cursor = end;
  }
  return blocks.concat(parseBlocks(text.slice(cursor)));
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

export function LessonContent({ text, className, omitFirstHeading, practiceScope }: LessonContentProps) {
  const lang = useLanguageStore(state => state.lang);
  const copy = visualLessonCopy(lang);
  const parsedBlocks = parseLesson(text);
  const path = practiceScope && parsedBlocks.some(block => block.type === 'youtube')
    ? practicePath(practiceScope.courseId, practiceScope.lessonId) : undefined;
  const [timedPractice, setTimedPractice] = useState<{ path: string; clip: VideoClip; practice: VideoPractice }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    void api.get<{ clip?: VideoClip; practice: VideoPractice | null }>(path, { signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted && data.clip && data.practice) {
          setTimedPractice({ path, clip: data.clip, practice: data.practice });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [path]);
  const firstBlock = parsedBlocks[0];
  const blocks = omitFirstHeading
    && firstBlock?.type === 'heading'
    && firstBlock.level === 1
    && firstBlock.text.trim() === omitFirstHeading.trim()
    ? parsedBlocks.slice(1)
    : parsedBlocks;

  function renderBlocks(items: RenderBlock[], prefix = 'block'): ReactNode[] {
    return (
      items.map((block, blockIndex) => {
        const key = `${prefix}-${blockIndex}`;

        if (block.type === 'disclosure') {
          const title = block.title.trim() || copy[block.kind];
          return <details key={`${key}:${block.kind}:${block.title}:${block.body}`} className="min-w-0 rounded-xl border border-border bg-card">
            <summary className="cursor-pointer break-words rounded-xl px-4 py-3 font-semibold marker:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
              {title}
            </summary>
            <div className="min-w-0 space-y-3 overflow-x-auto break-words border-t border-border px-4 py-3">
              {renderBlocks(parseBlocks(block.body), key)}
            </div>
          </details>;
        }

        if (block.type === 'image') return <figure key={key}>
          <AuthenticatedSourceImage url={block.url} alt={block.alt} />
          {(block.caption ?? block.alt) && <figcaption>{block.caption ?? block.alt}</figcaption>}
        </figure>;

        if (block.type === 'youtube') {
          const selected = timedPractice && timedPractice.path === path && practiceMatches(block.src, timedPractice.clip)
            ? timedPractice.practice : null;
          return selected && practiceScope
            ? <TimedPracticeVideo key={path + ':' + selected.at} src={block.src} title={block.title}
              practice={selected} language={practiceScope.language} />
            : <iframe key={key} title={block.title} src={block.src} loading="lazy" {...youtubeFrameProps} />;
        }

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
          const start = block.ordered ? block.items[0]?.value : undefined;
          const usesExplicitValues = block.ordered
            && block.items.some((item, itemIndex) => item.value !== (start ?? 1) + itemIndex);
          return (
            <List key={key} {...(start !== undefined ? { start } : {})}>
              {block.items.map((item, itemIndex) => (
                <li
                  key={`${key}-${itemIndex}`}
                  {...(usesExplicitValues ? { value: item.value } : {})}
                >
                  {renderInline(item.text, `${key}-${itemIndex}`)}
                </li>
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
      })
    );
  }

  return (
    <div className={className}>
      {renderBlocks(blocks)}
    </div>
  );
}
