import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

// jsdom is already the test runtime; keep this narrow harness typed without
// adding another dependency or weakening the application's TypeScript checks.
type GuideWindow = Window & typeof globalThis;
const { JSDOM } = createRequire(import.meta.url)('jsdom') as {
  JSDOM: new (source: string, options?: {
    url?: string;
    runScripts?: 'dangerously';
    beforeParse?: (window: GuideWindow) => void;
  }) => { window: GuideWindow };
};

const guidePath = path.resolve(process.cwd(), 'public/guides/methodologist-text.html');
const html = fs.readFileSync(guidePath, 'utf8');
const sourceManifestPath = path.resolve(__dirname, '../../../scripts/docs/methodologist_walkthrough.json');
const sourceManifestBytes = fs.readFileSync(sourceManifestPath);
const sourceManifest = JSON.parse(sourceManifestBytes.toString('utf8'));
const approvalPath = path.resolve(__dirname, 'fixtures/methodologist-guide-approval.json');
const approval = JSON.parse(fs.readFileSync(approvalPath, 'utf8'));
const sha = (data: Buffer) => crypto.createHash('sha256').update(data).digest('hex');
const sourceChapterIds = sourceManifest.chapters.map((chapter: { id: string }) => chapter.id);
const sourceImageCount = sourceManifest.chapters.reduce(
  (total: number, chapter: { segments: unknown[] }) => total + chapter.segments.length,
  0,
);
const expectedFlows = approval.chapter_ids;
const expectedImages = approval.verified_image_count;
const expectedHighlights = approval.verified_highlight_count;
const expectedOverlayScreens = approval.verified_overlay_screen_count;

describe('standalone methodologist instruction', () => {
  it('is covered by the root-owned approval record', () => {
    expect(approval.schema_version).toBe(1);
    expect(approval.status).toBe('APPROVED');
    expect(approval.review_status).toBe('APPROVED');
    expect(approval.media_folder).toBe('methodologist-qwen-male-20261113');
    expect(approval.chapter_ids).toEqual(sourceChapterIds);
    expect(approval.verified_step_count).toBe(sourceImageCount);
    expect(approval.verified_image_count).toBe(sourceImageCount);
    expect(approval.verified_capture_receipt_count).toBe(sourceImageCount);
    expect(approval.source_manifest_sha256).toBe(sha(sourceManifestBytes));
    expect(approval.html_sha256['methodologist-text.html']).toBe(sha(Buffer.from(html)));
    const mediaManifestBytes = fs.readFileSync(
      path.resolve(process.cwd(), 'public/guides/methodologist-qwen-male-20261113/manifest.json'),
    );
    expect(approval.media_manifest_sha256).toBe(sha(mediaManifestBytes));
  });

  it('covers the eight human stages, using only embedded production screenshots', () => {
    const dom = new JSDOM(html);
    const document = dom.window.document;
    expect([...document.querySelectorAll('.flow')].map((el) => el.id)).toEqual(expectedFlows);
    expect(document.querySelectorAll('.image-frame img')).toHaveLength(expectedImages);
    expect(document.querySelectorAll('[data-highlight]')).toHaveLength(expectedHighlights);
    expect(document.querySelectorAll('.overlay')).toHaveLength(expectedOverlayScreens);
    expect(document.querySelectorAll('.overlay g')).toHaveLength(expectedHighlights);
    for (const image of document.querySelectorAll('img')) {
      expect(image.getAttribute('src')).toMatch(/^data:image\/png;base64,/);
      expect(image.getAttribute('alt')).toBeTruthy();
    }
    for (const link of document.querySelectorAll('a[href^="#"]')) {
      expect(document.getElementById(link.getAttribute('href')!.slice(1))).not.toBeNull();
    }
    expect(document.querySelectorAll('script[src], link, iframe, object, audio, video, form')).toHaveLength(0);
    expect(html).not.toMatch(/@import|\bfetch\s*\(|XMLHttpRequest|WebSocket|url\(/);
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toContain("connect-src 'none'");
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toContain("default-src 'none'");
    expect(document.body.textContent).toContain('Мужской синтетический голос Qwen3-TTS');
    expect(document.body.textContent).toContain('«Опубликовать»');
    expect(document.body.textContent).toContain('«Одобрить после проверки»');
    expect(document.body.textContent).toContain('«Завершить курс»');
    expect(document.querySelectorAll('.flow a[href^="/admin/"]')).toHaveLength(0);
    const style = document.querySelector('style')!.textContent!;
    expect(style).toContain('max-height:calc(100vh - 52px);overflow:auto');
    expect(style).toContain('.image-frame img{display:block;max-width:100%;height:auto');
    expect(style).toContain('.zoom-content .image-frame{width:max-content}');
    expect(style).toContain('.zoom-content img{display:block;max-width:none;width:auto;height:auto');
    expect(style).not.toContain('width:min(100%,1600px)');
    dom.window.close();
  });

  it('runs progress, highlights and zoom without network or adjacent files', () => {
    const requests: string[] = [];
    const dom = new JSDOM(html, {
      url: 'file:///isolated-copy/methodologist.html',
      runScripts: 'dangerously',
      beforeParse(window) {
        window.fetch = async (input) => {
          requests.push(String(input));
          throw new Error('Network disabled in standalone guide test');
        };
      },
    });
    const { document, Event, KeyboardEvent } = dom.window;
    const check = document.querySelector<HTMLInputElement>('[data-complete="01-sources"]')!;
    check.checked = true;
    check.dispatchEvent(new Event('change'));
    expect(document.querySelector<HTMLProgressElement>('#pilot-progress')!.value).toBe(1);
    expect(document.querySelector('#pilot-progress')!.textContent).toBe('1 из 8');
    document.querySelector<HTMLButtonElement>('#reset-progress')!.click();
    expect(document.querySelector<HTMLProgressElement>('#pilot-progress')!.value).toBe(0);
    const button = document.querySelector<HTMLButtonElement>('[data-highlight]');
    if (button) {
      button.click();
      expect(button.getAttribute('aria-pressed')).toBe('true');
      expect(document.querySelectorAll('.overlay g.active')).toHaveLength(1);
    } else {
      expect(expectedHighlights).toBe(0);
    }
    const zoom = document.querySelector<HTMLButtonElement>('[data-zoom]')!;
    zoom.focus();
    zoom.click();
    expect(document.querySelector<HTMLElement>('#zoom')!.hidden).toBe(false);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.querySelector<HTMLElement>('#zoom')!.hidden).toBe(true);
    expect(document.activeElement).toBe(zoom);
    expect(requests).toEqual([]);
    expect(document.querySelector<HTMLButtonElement>('#download-guide')!.textContent).toContain('Скачать HTML');
    dom.window.close();
  });

  it('keeps quiz-result guidance static inside the document body', () => {
    expect(html).toContain('Бланк результата отдельного теста');
    expect(html).toContain('Скачать результат теста');
    expect(html).toContain('Скачать PDF');
    expect(html).toContain('три отдельных текста');
    const closingHtml = html.toLowerCase().lastIndexOf('</html>');
    expect(closingHtml).toBeGreaterThan(-1);
    expect(html.slice(closingHtml + '</html>'.length).trim()).toBe('');
    expect(html.slice(0, closingHtml).lastIndexOf('Бланк результата отдельного теста')).toBeGreaterThan(-1);
    const dom = new JSDOM(html);
    const guidance = dom.window.document.querySelector('#quiz-result-form-guidance')?.parentElement;
    expect(guidance?.tagName).toBe('SECTION');
    expect(guidance?.parentElement?.id).toBe('08-results');
    expect(guidance?.parentElement?.classList.contains('flow')).toBe(true);
    expect(dom.window.document.querySelectorAll('#quiz-result-form-guidance')).toHaveLength(1);
    dom.window.close();
  });
});
