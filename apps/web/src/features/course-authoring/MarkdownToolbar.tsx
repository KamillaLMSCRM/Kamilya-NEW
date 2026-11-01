'use client';

import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Button } from '@/components/ui';
import { authorWorkspaceCopy } from './authorWorkspaceCopy';

export type MarkdownFormat = 'bold' | 'italic' | 'heading' | 'bullets' | 'numbered' | 'quote' | 'code';
const formats: MarkdownFormat[] = ['bold', 'italic', 'heading', 'bullets', 'numbered', 'quote', 'code'];

// A selection edit on the canonical text, not a Markdown parser or HTML conversion.
export function formatMarkdown(value: string, start: number, end: number, format: MarkdownFormat, placeholder: string) {
  if (format === 'bold' || format === 'italic' || format === 'code') {
    const marker = format === 'bold' ? '**' : format === 'italic' ? '*' : '`';
    const selected = value.slice(start, end) || placeholder;
    if (selected.includes('\n')) {
      // The existing renderer handles inline formatting one line at a time.
      const formatted = selected.split('\n').map((line) => {
        const body = line.endsWith('\r') ? line.slice(0, -1) : line;
        return body ? marker + body + marker + (line.endsWith('\r') ? '\r' : '') : line;
      }).join('\n');
      return { value: value.slice(0, start) + formatted + value.slice(end), start, end: start + formatted.length };
    }
    return {
      value: value.slice(0, start) + marker + selected + marker + value.slice(end),
      start: start + marker.length, end: start + marker.length + selected.length,
    };
  }
  const from = start === 0 ? 0 : value.lastIndexOf('\n', start - 1) + 1;
  const selectionEnd = end > start && value[end - 1] === '\n' ? end - 1 : end;
  const nextNewline = value.indexOf('\n', selectionEnd);
  const to = nextNewline < 0 ? value.length : nextNewline;
  const lines = value.slice(from, to).split('\n');
  const formatted = lines.map((line, index) => {
    const prefix = format === 'heading' ? '## ' : format === 'bullets' ? '- ' : format === 'quote' ? '> ' : `${index + 1}. `;
    return prefix + line;
  }).join('\n');
  return { value: value.slice(0, from) + formatted + value.slice(to), start: from, end: from + formatted.length };
}

export function MarkdownToolbar({ value, onChange, textareaRef, lang }: {
  value: string; onChange: (value: string) => void; textareaRef: RefObject<HTMLTextAreaElement>; lang?: string;
}) {
  const copy = authorWorkspaceCopy(lang);
  const [selection, setSelection] = useState<{ start: number; end: number } | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!selection || !textareaRef.current) return;
    textareaRef.current.focus();
    textareaRef.current.setSelectionRange(selection.start, selection.end);
    setSelection(null);
  }, [selection, textareaRef]);

  return <div className="space-y-2">
    <div ref={toolbarRef} role="toolbar" aria-label={copy.formatting} className="flex flex-wrap gap-1 rounded-md border border-border p-1" onKeyDown={(event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const buttons = Array.from(toolbarRef.current?.querySelectorAll<HTMLButtonElement>('button') ?? []);
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }}>
      {formats.map((format) => <Button key={format} type="button" size="sm" variant="ghost" aria-label={copy[format]} onMouseDown={(event) => event.preventDefault()} onClick={() => {
        const textarea = textareaRef.current;
        if (!textarea || textarea.disabled || textarea.matches(':disabled')) return;
        const edit = formatMarkdown(value, textarea.selectionStart, textarea.selectionEnd, format, copy.text);
        onChange(edit.value); setSelection({ start: edit.start, end: edit.end });
      }}>{copy[format]}</Button>)}
    </div>
    <p className="text-xs leading-5 text-muted-foreground">{copy.formatHint}</p>
  </div>;
}
