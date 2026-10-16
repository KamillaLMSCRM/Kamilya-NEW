import fs from 'node:fs';
import path from 'node:path';
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

describe('standalone methodologist instruction', () => {
  it('covers the eight human stages, using only embedded production screenshots', () => {
    const dom = new JSDOM(html);
    const document = dom.window.document;
    expect([...document.querySelectorAll('.flow')].map((el) => el.id)).toEqual([
      'sources', 'generation', 'lessons', 'tests', 'publication', 'staff', 'assignment', 'results',
    ]);
    expect(document.querySelectorAll('.image-frame img')).toHaveLength(24);
    expect(document.querySelectorAll('[data-highlight]')).toHaveLength(77);
    for (const image of document.querySelectorAll('img')) {
      expect(image.getAttribute('src')).toMatch(/^data:image\/jpeg;base64,/);
      expect(image.getAttribute('alt')).toBeTruthy();
    }
    for (const link of document.querySelectorAll('a[href^="#"]')) {
      expect(document.getElementById(link.getAttribute('href')!.slice(1))).not.toBeNull();
    }
    expect(document.querySelectorAll('script[src], link, iframe, object, audio, video, form')).toHaveLength(0);
    expect(html).not.toMatch(/@import|\bfetch\s*\(|XMLHttpRequest|WebSocket|url\(/);
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toContain("connect-src 'none'");
    expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content')).toContain("default-src 'none'");
    expect(document.body.textContent).toContain('production 0.11.47');
    expect(document.body.textContent).toContain('«Опубликовать»');
    expect(document.body.textContent).toContain('«Одобрить после проверки»');
    expect(document.body.textContent).toContain('«Завершить курс»');
    expect(document.querySelectorAll('.flow a[href^="/admin/"]')).toHaveLength(0);
    expect(document.querySelector('style')!.textContent).toContain('max-height:calc(100vh - 52px);overflow:auto');
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
    const check = document.querySelector<HTMLInputElement>('[data-complete="sources"]')!;
    check.checked = true;
    check.dispatchEvent(new Event('change'));
    expect(document.querySelector<HTMLProgressElement>('#pilot-progress')!.value).toBe(1);
    expect(document.querySelector('#pilot-progress')!.textContent).toBe('1 из 8');
    document.querySelector<HTMLButtonElement>('#reset-progress')!.click();
    expect(document.querySelector<HTMLProgressElement>('#pilot-progress')!.value).toBe(0);
    const button = document.querySelector<HTMLButtonElement>('[data-highlight]')!;
    button.click();
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelectorAll('.overlay g.active')).toHaveLength(1);
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
});
