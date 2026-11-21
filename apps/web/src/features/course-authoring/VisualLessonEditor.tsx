'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui';
import axios from 'axios';
import { isUploadedLessonImage, lessonImageMarkdown, sourceImageLine } from '@/components/AuthenticatedSourceImage';
import { api } from '@/lib/api';
import { LessonContent, lessonContentClassName } from './LessonContent';
import { MarkdownToolbar } from './MarkdownToolbar';
import { joinLessonBlocks, lessonBlockKind, replaceLessonBlock, separateLessonBlocks, splitLessonBlocks, type LessonBlock, type LessonBlockKind } from './lessonBlocks';
import { readLessonDisclosure, writeLessonDisclosure } from './lessonDisclosure';
import { visualLessonCopy } from './visualLessonCopy';

export function VisualLessonEditor({ value, onChange, lang, disabled: readOnly = false, illustrationEndpoint }: {
  value: string; onChange: (value: string) => void; lang?: string; disabled?: boolean; illustrationEndpoint?: string;
}) {
  const copy = visualLessonCopy(lang);
  const id = useId();
  const [blocks, setBlocks] = useState(() => splitLessonBlocks(value));
  const [selected, setSelected] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadRequest = useRef<AbortController | null>(null);
  const disabled = readOnly || uploading;
  useEffect(() => () => uploadRequest.current?.abort(), []);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const expected = useRef(value);
  const root = useRef<HTMLDivElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const focusIndex = useRef<number | null>(null);
  const [imageLibrary, setImageLibrary] = useState(() => splitLessonBlocks(value).flatMap(block => sourceImageLine(block.markdown)?.url ? [block.markdown.trim()] : []));
  useEffect(() => {
    if (value === expected.current) return;
    expected.current = value;
    const next = splitLessonBlocks(value);
    setBlocks(next); setSelected(null); setDeleting(null); setShowAdd(false);
    setImageLibrary(next.flatMap(block => sourceImageLine(block.markdown) ? [block.markdown.trim()] : []));
  }, [value]);
  useEffect(() => {
    if (focusIndex.current === null) return;
    root.current?.querySelector<HTMLButtonElement>(`[data-block-select="${focusIndex.current}"]`)?.focus();
    focusIndex.current = null;
  }, [blocks]);
  const images = useMemo(() => [...new Set(imageLibrary)], [imageLibrary]);
  function emit(next: LessonBlock[]) {
    expected.current = joinLessonBlocks(next);
    setBlocks(next); onChange(expected.current);
  }
  function add(kind: LessonBlockKind) {
    if (disabled) return;
    if (kind === 'hint' || kind === 'example') {
      insert(writeLessonDisclosure({ kind, title: copy[kind], body: '' }));
      return;
    }
    const markdown = { text: copy.newText, heading: `## ${copy.newHeading}`, rule: `> ${copy.newRule}`, steps: copy.newSteps, image: images[0] }[kind];
    if (!markdown) return;
    insert(markdown);
  }
  function insert(markdown: string) {
    const index = selected === null ? blocks.length : selected + 1;
    const next = [...blocks]; next.splice(index, 0, { markdown, after: '' });
    emit(separateLessonBlocks(next)); setSelected(index); setDeleting(null); setShowAdd(false);
    focusIndex.current = index; setAnnouncement(copy.added);
  }
  async function upload(file?: File) {
    if (!file || !illustrationEndpoint || disabled || uploadRequest.current) return;
    setUploadError('');
    if (file.size === 0 || file.size > 5 * 1024 * 1024 || !/\.(?:png|jpe?g)$/i.test(file.name)) {
      setUploadError(copy.imageInvalid);
      return;
    }
    const controller = new AbortController();
    uploadRequest.current = controller;
    setUploading(true);
    const priorValue = expected.current;
    const body = new FormData();
    body.append('file', file);
    try {
      const { data } = await api.post<{ url: string }>(illustrationEndpoint, body, { headers: { 'Content-Type': 'multipart/form-data' }, signal: controller.signal });
      if (controller.signal.aborted || expected.current !== priorValue) return;
      if (!isUploadedLessonImage(data.url)) throw new Error('Invalid illustration URL');
      const markdown = lessonImageMarkdown(data.url, '', '');
      setImageLibrary(previous => [...previous, markdown]);
      insert(markdown);
    } catch (error) {
      if (!controller.signal.aborted) {
        const status = axios.isAxiosError(error) ? error.response?.status : undefined;
        setUploadError(status === 413 || status === 422 ? copy.imageInvalid : copy.imageUploadError);
      }
    } finally {
      if (uploadRequest.current === controller) uploadRequest.current = null;
      if (!controller.signal.aborted) setUploading(false);
    }
  }
  function move(index: number, delta: number) {
    const target = index + delta;
    if (disabled || target < 0 || target >= blocks.length) return;
    const next = [...blocks]; [next[index], next[target]] = [next[target], next[index]];
    emit(separateLessonBlocks(next)); setSelected(target); setDeleting(null);
    focusIndex.current = target; setAnnouncement(copy.moved);
  }
  function remove(index: number) {
    if (disabled) return;
    emit(blocks.filter((_, item) => item !== index)); setDeleting(null);
    const next = blocks.length > 1 ? Math.min(index, blocks.length - 2) : null;
    setSelected(next); focusIndex.current = next; setAnnouncement(copy.removed);
    if (next === null) addButton.current?.focus();
  }
  return <div ref={root} className="min-w-0 space-y-3" aria-label={copy.blocks}>
    <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm font-medium">{copy.blocks} · {blocks.length}</p>
      <Button ref={addButton} type="button" size="sm" variant="outline" disabled={disabled} aria-expanded={showAdd} onClick={() => setShowAdd(!showAdd)}><Plus className="mr-1 h-4 w-4" aria-hidden="true" />{copy.add}</Button>
    </div>
    {showAdd && <div className="flex flex-wrap gap-2 rounded-xl border border-border bg-muted/30 p-3" role="group" aria-label={copy.add}>
      {(['text', 'heading', 'rule', 'steps', 'hint', 'example', 'image'] as const).map(kind => <Button key={kind} type="button" size="sm" variant="outline" disabled={disabled || (kind === 'image' && !images.length)} onClick={() => add(kind)}>{copy[kind]}</Button>)}
      {illustrationEndpoint && <div className="flex flex-wrap items-center gap-2">
        <input aria-label={copy.upload} ref={fileInput} type="file" hidden accept=".png,.jpg,.jpeg,image/png,image/jpeg" onChange={event => {
          const file = event.target.files?.[0];
          event.target.value = '';
          void upload(file);
        }} />
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => fileInput.current?.click()}>{uploading ? copy.uploading : copy.upload}</Button>
        <span className="text-xs text-muted-foreground">{copy.imageLimit}</span>
      </div>}
      {uploadError && <p role="alert" className="w-full text-sm text-destructive">{uploadError}</p>}
      {!images.length && <p className="w-full text-xs text-muted-foreground">{copy.noImages}</p>}
    </div>}
    {!blocks.length && <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{copy.empty}</p>}
    {blocks.map((block, index) => {
      const kind = lessonBlockKind(block.markdown);
      const disclosure = kind === 'hint' || kind === 'example' ? readLessonDisclosure(block.markdown) : undefined;
      const illustration = sourceImageLine(block.markdown);
      const uploaded = illustration ? isUploadedLessonImage(illustration.url) : false;
      const kindLabel = uploaded ? copy.uploaded : copy[kind];
      const isSelected = selected === index;
      return <section key={index} aria-label={`${kindLabel} ${index + 1}`} className={`min-w-0 overflow-hidden rounded-xl border ${isSelected ? 'border-primary ring-1 ring-primary/20' : 'border-border'} bg-card`}>
        <div className="flex flex-wrap items-center gap-1 border-b border-border bg-muted/20 px-3 py-2">
          <Button data-block-select={index} className="mr-auto h-auto min-h-9 whitespace-normal text-left" type="button" size="sm" variant="ghost" disabled={disabled} aria-expanded={isSelected} aria-controls={`${id}-${index}`} onClick={() => { setSelected(isSelected ? null : index); setDeleting(null); }}><Pencil className="mr-1.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{index + 1}. {kindLabel}</Button>
          <Button type="button" size="sm" variant="ghost" disabled={disabled || index === 0} aria-label={`${copy.up}: ${index + 1}`} onClick={() => move(index, -1)}><ArrowUp className="h-4 w-4" aria-hidden="true" /></Button>
          <Button type="button" size="sm" variant="ghost" disabled={disabled || index === blocks.length - 1} aria-label={`${copy.down}: ${index + 1}`} onClick={() => move(index, 1)}><ArrowDown className="h-4 w-4" aria-hidden="true" /></Button>
          <Button type="button" size="sm" variant="ghost" disabled={disabled} aria-label={`${copy.remove}: ${index + 1}`} aria-expanded={deleting === index} onClick={() => setDeleting(deleting === index ? null : index)}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button>
        </div>
        {deleting === index && <div role="group" aria-label={copy.confirm} className="flex flex-wrap items-center gap-2 border-b border-border bg-destructive/5 p-3"><span className="mr-auto text-sm">{copy.confirm}</span><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => { setDeleting(null); root.current?.querySelector<HTMLButtonElement>(`[data-block-select="${index}"]`)?.focus(); }}>{copy.cancel}</Button><Button type="button" size="sm" disabled={disabled} onClick={() => remove(index)}>{copy.remove}</Button></div>}
        <div id={`${id}-${index}`}>
          {isSelected && <div className="space-y-2 border-b border-border p-3 sm:p-4">
            {!disclosure && <label htmlFor={`${id}-content-${index}`} className="text-sm font-medium">{copy.body}</label>}
            <fieldset disabled={disabled} className="min-w-0 space-y-2">
              {kind === 'heading' ? <input id={`${id}-content-${index}`} aria-label={`${copy.body}: ${index + 1}`} value={block.markdown.replace(/\r?\n$/, '').replace(/^#{1,6} /, '')} className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xl font-semibold" onChange={event => emit(replaceLessonBlock(blocks, index, `${block.markdown.match(/^#{1,6}/)?.[0] ?? '##'} ${event.target.value}`))} />
                : kind === 'rule' ? <textarea id={`${id}-content-${index}`} aria-label={`${copy.body}: ${index + 1}`} value={block.markdown.replace(/^> ?/gm, '').replace(/\r?\n$/, '')} rows={4} className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 text-base leading-7" onChange={event => emit(replaceLessonBlock(blocks, index, event.target.value.split('\n').map(line => `> ${line}`).join('\n')))} />
                  : kind === 'steps' ? <div id={`${id}-content-${index}`} className="space-y-2">
                    {block.markdown.replace(/(?:\r?\n)+$/, '').split(/\r?\n/).map((line, step) => {
                      const match = line.match(/^(\d+[.)]\s+)(.*)$/)!;
                      return <label key={step} className="flex items-start gap-2"><span className="py-2 text-sm text-muted-foreground">{match[1]}</span><input aria-label={`${copy.steps}: ${step + 1}`} value={match[2]} className="min-w-0 flex-1 rounded-lg border border-input bg-background px-3 py-2 text-base" onChange={event => {
                        const lines = block.markdown.split(/(\r?\n)/); lines[step * 2] = match[1] + event.target.value;
                        emit(replaceLessonBlock(blocks, index, lines.join('')));
                      }} /></label>;
                    })}
                  </div> : disclosure ? <>
                    <label className="block space-y-1 text-sm font-medium">{copy.disclosureTitle}
                      <input value={disclosure.title} className="block w-full rounded-lg border border-input bg-background px-3 py-2 text-base" onChange={event => {
                        emit(replaceLessonBlock(blocks, index, writeLessonDisclosure({ ...disclosure, title: event.target.value })));
                      }} />
                    </label>
                    <label htmlFor={`${id}-content-${index}`} className="text-sm font-medium">{copy.body}</label>
                    <MarkdownToolbar value={disclosure.body} onChange={body => emit(replaceLessonBlock(blocks, index, writeLessonDisclosure({ ...disclosure, body })))} textareaRef={textarea} lang={lang} />
                    <textarea ref={textarea} id={`${id}-content-${index}`} value={disclosure.body} rows={5} className="w-full min-w-0 resize-y rounded-lg border border-input bg-background px-3 py-2 text-base leading-7" onChange={event => {
                      emit(replaceLessonBlock(blocks, index, writeLessonDisclosure({ ...disclosure, body: event.target.value })));
                    }} />
                  </> : illustration ? <div id={`${id}-content-${index}`} className="space-y-3">
                    <label className="block space-y-1 text-sm">{copy.selectImage}<select aria-label={copy.selectImage} value={illustration.url} className="block w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2" onChange={event => {
                      const image = images.find(item => sourceImageLine(item)?.url === event.target.value);
                      if (image) emit(replaceLessonBlock(blocks, index, image));
                    }}>{images.map((image, at) => { const parsed = sourceImageLine(image)!; return <option key={`${parsed.url}:${at}`} value={parsed.url}>{parsed.alt || `${copy.image} ${at + 1}`}</option>; })}</select></label>
                    {uploaded && <label className="block space-y-1 text-sm">{copy.alt}
                      <input maxLength={300} value={illustration.alt} className="block w-full rounded-lg border border-input bg-background px-3 py-2 text-base" onChange={event => {
                        emit(replaceLessonBlock(blocks, index, lessonImageMarkdown(illustration.url, event.target.value, illustration.caption ?? '')));
                      }} />
                    </label>}
                    <label className="block space-y-1 text-sm">{copy.caption}
                      <input aria-label={copy.caption} maxLength={300} value={uploaded ? illustration.caption ?? '' : illustration.alt} className="block w-full rounded-lg border border-input bg-background px-3 py-2 text-base" onChange={event => {
                        const value = event.target.value;
                        emit(replaceLessonBlock(blocks, index, lessonImageMarkdown(illustration.url, uploaded ? illustration.alt : value, uploaded ? value : undefined)));
                      }} />
                    </label>
                  </div> : <>
                    <MarkdownToolbar value={block.markdown} onChange={markdown => emit(replaceLessonBlock(blocks, index, markdown))} textareaRef={textarea} lang={lang} />
                    <textarea ref={textarea} id={`${id}-content-${index}`} value={block.markdown} aria-label={`${copy.body}: ${index + 1}`} onChange={event => emit(replaceLessonBlock(blocks, index, event.target.value))} rows={Math.min(16, Math.max(3, block.markdown.split('\n').length + 1))} className="w-full min-w-0 resize-y rounded-lg border border-input bg-background px-3 py-2 text-base leading-7 focus:outline-none focus:ring-2 focus:ring-primary" />
                  </>}
            </fieldset>
            <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => { setSelected(null); root.current?.querySelector<HTMLButtonElement>(`[data-block-select="${index}"]`)?.focus(); }}>{copy.done}</Button>
          </div>}
          <div className="overflow-x-auto break-words p-4 sm:p-5" aria-label={copy.preview}><LessonContent text={block.markdown} className={lessonContentClassName} /></div>
        </div>
      </section>;
    })}
  </div>;
}
