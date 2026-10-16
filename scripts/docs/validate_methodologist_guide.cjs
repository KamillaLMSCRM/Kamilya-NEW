const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const taskDir = path.resolve(__dirname, '../../outputs/methodologist-production-guide-20261013');
const { JSDOM, VirtualConsole } = require(path.resolve(taskDir, '../../apps/web/node_modules/jsdom'));
const sharp = require('C:/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');

async function main() {
  const htmlPath = path.resolve(__dirname, '../../apps/web/public/guides/methodologist-text.html');
  const html = fs.readFileSync(htmlPath, 'utf8');
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (error) => errors.push(error.message));
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole });
  const { window } = dom;
  const document = window.document;
  assert.deepEqual(errors, []);
  assert.equal(document.querySelectorAll('.flow').length, 8);
  assert.equal(document.querySelectorAll('.image-frame img').length, 24);
  assert.equal(document.querySelectorAll('script').length, 1);
  assert.equal(document.querySelectorAll('script[src],link,iframe,object,video,audio').length, 0);
  assert.ok(!/\bfetch\s*\(|XMLHttpRequest|WebSocket|@import|url\(/.test(html));
  const ids = [...document.querySelectorAll('[id]')].map(el => el.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const a of document.querySelectorAll('a[href^="#"]')) {
    assert.ok(document.getElementById(a.getAttribute('href').slice(1)), a.getAttribute('href'));
  }
  const metadata = JSON.parse(fs.readFileSync(path.join(taskDir, 'normalized-marks.json'), 'utf8'));
  for (const img of document.querySelectorAll('.image-frame img')) {
    const name = img.parentElement.dataset.image;
    assert.ok(img.src.startsWith('data:image/jpeg;base64,'));
    const raw = Buffer.from(img.src.split(',')[1], 'base64');
    assert.equal(crypto.createHash('sha256').update(raw).digest('hex'), metadata[name].sha256);
    assert.deepEqual(raw, fs.readFileSync(path.join(taskDir, 'screens', name + '.jpg')));
    assert.equal(img.width, metadata[name].width);
    assert.equal(img.height, metadata[name].height);
    const buttons = [...img.closest('.screen').querySelectorAll('[data-highlight]')];
    assert.equal(buttons.length, metadata[name].marks.length);
    for (const button of buttons) {
      button.click();
      assert.equal(button.getAttribute('aria-pressed'), 'true');
      assert.equal(button.closest('.screen').querySelectorAll('.overlay g.active').length, 1);
      button.click();
      assert.equal(button.getAttribute('aria-pressed'), 'false');
      assert.equal(button.closest('.screen').querySelectorAll('.overlay g.active').length, 0);
    }
  }
  const checks = [...document.querySelectorAll('[data-complete]')];
  checks.forEach(el => { el.checked = true; el.dispatchEvent(new window.Event('change')); });
  assert.equal(document.getElementById('pilot-progress').value, 8);
  assert.equal(document.querySelectorAll('.nav a.done').length, 8);
  document.getElementById('reset-progress').click();
  assert.equal(document.getElementById('pilot-progress').value, 0);
  for (const button of document.querySelectorAll('[data-zoom]')) {
    button.click();
    assert.equal(document.getElementById('zoom').hidden, false);
    assert.equal(document.getElementById('zoom-content').querySelectorAll('img').length, 1);
    assert.ok(document.body.classList.contains('zoom-open'));
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(document.getElementById('zoom').hidden, true);
    assert.equal(document.getElementById('zoom-content').childElementCount, 0);
    assert.ok(!document.body.classList.contains('zoom-open'));
    assert.equal(document.activeElement, button);
  }
  let printed = false;
  window.print = () => { printed = true; };
  document.getElementById('print-guide').click();
  assert.ok(printed);
  assert.equal(document.querySelectorAll('.screen[open]').length, 24);
  assert.deepEqual(errors, []);
  const qa = path.join(taskDir, 'qa');
  for (const name of Object.keys(metadata)) {
    await sharp(fs.readFileSync(path.join(qa, name + '.svg'))).png().toFile(path.join(qa, name + '.png'));
  }
  const report = {
    result: 'PASS', flows: 8, real_screenshots: 24,
    embedded_frame_bytes_match_stored_frames: true,
    external_render_dependencies: 0,
    hotspot_toggle_tests: document.querySelectorAll('[data-highlight]').length,
    zoom_open_escape_focus_tests: 24,
    progress_check_reset: 'PASS', print_expands_all: 'PASS',
    renderer: 'SVG overlays through bundled Sharp; embedded frames match stored deterministic crops; raw browser JPEGs retained separately',
    dom_tests: 'existing Kamilya jsdom loaded by bundled Node, no browser navigation or network',
    html_sha256: crypto.createHash('sha256').update(html).digest('hex'),
    whole_html_browser_visual_review: 'NOT_RUN: separate controlled browser review required',
    annotated_screens_visual_review: 'PENDING_ROOT_ALL24',
  };
  fs.writeFileSync(path.join(taskDir, 'validation.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  dom.window.close();
}
main().catch(error => { console.error(error); process.exitCode = 1; });
