// The published files, not the importer's implementation, are the test oracle.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { describe, expect, it, vi } from 'vitest';

const { JSDOM } = createRequire(import.meta.url)('jsdom') as {
  JSDOM: new (source: string, options: { runScripts: 'dangerously' }) => { window: Window & typeof globalThis };
};

const guideDir = path.resolve(__dirname, '../public/guides');
const html = fs.readFileSync(path.join(guideDir, 'methodologist.html'), 'utf8');
const mediaDir = path.join(guideDir, 'methodologist-qwen-male');
const manifest = JSON.parse(fs.readFileSync(path.join(mediaDir, 'manifest.json'), 'utf8'));
const sha = (data: Buffer) => crypto.createHash('sha256').update(data).digest('hex');
const expectedSteps = [12, 8, 7, 9, 7, 10, 9, 7];

describe('published male Qwen methodologist video guide', () => {
  it('contains the complete approved eight-process, 69-step series', () => {
    document.documentElement.innerHTML = html;
    expect(document.querySelectorAll('video')).toHaveLength(8);
    expect(document.querySelectorAll('button[data-seek]')).toHaveLength(69);
    expect(document.querySelectorAll('track[kind="captions"][srclang="ru"]')).toHaveLength(8);
    expect(html).toContain('Мужской синтетический голос Qwen3-TTS');
    expect(manifest.videos.map((v: { steps: number }) => v.steps)).toEqual(expectedSteps);
    for (const [index, video] of [...document.querySelectorAll('video')].entries()) {
      const buttons = document.querySelectorAll(`button[data-video="${manifest.videos[index].id}"]`);
      expect(buttons).toHaveLength(expectedSteps[index]);
      expect(video.getAttribute('preload')).toBe('metadata');
      expect(video.hasAttribute('autoplay')).toBe(false);
      const starts = [...buttons].map(b => Number((b as HTMLElement).dataset.seek));
      expect(starts[0]).toBe(0);
      expect(starts).toEqual([...starts].sort((a, b) => a - b));
      expect(starts.at(-1)).toBeLessThan(manifest.videos[index].duration_seconds);
    }
  });

  it('serves exactly the approved media bytes and valid caption intervals', () => {
    expect(manifest.assets).toHaveLength(32);
    for (const asset of manifest.assets) {
      expect(asset.name).toMatch(/^[0-9]{2}-[a-z]+(?:-poster)?\.(mp4|jpg|srt|vtt)$/);
      const bytes = fs.readFileSync(path.join(mediaDir, asset.name));
      expect(bytes.length).toBe(asset.bytes);
      expect(sha(bytes)).toBe(asset.sha256);
      if (asset.name.endsWith('.mp4')) {
        expect(bytes.subarray(4, 8).toString()).toBe('ftyp');
        expect(bytes.indexOf(Buffer.from('moov'))).toBeLessThan(bytes.indexOf(Buffer.from('mdat')));
      }
    }
    for (const video of manifest.videos) {
      const vtt = fs.readFileSync(path.join(mediaDir, `${video.id}.vtt`), 'utf8');
      expect(vtt.startsWith('WEBVTT')).toBe(true);
      expect(vtt.match(/ --> /g)).toHaveLength(video.steps);
      expect(sha(fs.readFileSync(path.join(mediaDir, `${video.id}.mp4`)))).toBe(video.sha256);
    }
  });

  it('uses only existing same-origin assets and preserves the screenshot guide', () => {
    document.documentElement.innerHTML = html;
    expect(document.querySelectorAll('iframe,object,script[src],link')).toHaveLength(0);
    expect(html).not.toMatch(/\bfetch\s*\(|XMLHttpRequest|WebSocket|https?:\/\//);
    expect(html).toContain("media-src 'self'");
    expect(html).toContain("connect-src 'none'");
    for (const element of document.querySelectorAll('[src],[poster],a[href]')) {
      for (const attr of ['src', 'poster', 'href']) {
        const value = element.getAttribute(attr);
        if (!value || value === '/' || value.startsWith('#')) continue;
        expect(value).not.toMatch(/^(?:[a-z]+:|\/\/)|\.\./i);
        expect(fs.existsSync(path.join(guideDir, value))).toBe(true);
      }
    }
    const legacy = fs.readFileSync(path.join(guideDir, 'methodologist-text.html'), 'utf8');
    expect(legacy).toContain('pilot-progress');
    expect(legacy.match(/class="flow"/g)).toHaveLength(8);
  });

  it('keeps quiz-result guidance static before the closing html tag', () => {
    expect(html).toContain('Настройку бланка выполняет администратор');
    expect(html).toContain('Скачать результат теста');
    expect(html).toContain('Скачать PDF');
    const closingHtml = html.toLowerCase().lastIndexOf('</html>');
    expect(closingHtml).toBeGreaterThan(-1);
    expect(html.slice(closingHtml + '</html>'.length).trim()).toBe('');
    expect(html.slice(0, closingHtml).lastIndexOf('Настройку бланка выполняет администратор')).toBeGreaterThan(-1);
  });

  it('seeks every chapter while paused and prevents simultaneous narration', () => {
    const dom = new JSDOM(html, { runScripts: 'dangerously' });
    const doc = dom.window.document;
    const videos = [...doc.querySelectorAll('video')];
    const pauses = videos.map(video => vi.spyOn(video, 'pause').mockImplementation(() => {}));
    videos.forEach(video => { video.scrollIntoView = vi.fn(); });
    for (const button of doc.querySelectorAll<HTMLButtonElement>('button[data-seek]')) {
      button.click();
      const video = doc.getElementById(`video-${button.dataset.video}`) as HTMLVideoElement;
      expect(video.currentTime).toBe(Number(button.dataset.seek));
      expect(video.pause).toHaveBeenCalled();
    }
    pauses.forEach(pause => pause.mockClear());
    videos[0].dispatchEvent(new dom.window.Event('play'));
    expect(pauses[0]).not.toHaveBeenCalled();
    pauses.slice(1).forEach(pause => expect(pause).toHaveBeenCalledOnce());
    dom.window.close();
  });
});
