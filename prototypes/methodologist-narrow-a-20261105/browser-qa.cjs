const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const localRequire = createRequire(path.resolve(__dirname, '../../apps/web/package.json'));
const { chromium } = localRequire('@playwright/test');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const output = path.join(__dirname, 'evidence');
  fs.mkdirSync(output, { recursive: true });
  const results = [];
  try {
    for (const width of [390, 768, 1270, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' });
      let requests = 0;
      await context.route(/^https?:/, route => { requests++; return route.abort(); });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(pathToFileURL(path.join(__dirname, 'index.html')).href);
      await page.getByRole('heading', { name: 'Задачи', exact: true }).waitFor();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow ${width}`);
      await page.screenshot({ path: path.join(output, `tasks-${width}.png`), fullPage: true });
      await page.locator('[data-filter="review"]').click();
      assert.equal(await page.locator('[data-task]').count(), 1);
      await page.locator('[data-task="review"]').click();
      if (width <= 900) assert.equal(await page.evaluate(() => document.activeElement.id), 'task-detail');
      await page.locator('[data-action="review"]').click();
      await page.locator('[data-tab="agreement"]').first().click();
      assert.match(await page.locator('#view').innerText(), /не принимается|не отправляется/);
      await page.locator('[data-tab="prep"]').first().click();
      assert.match(await page.locator('#view').innerText(), /Правильный ответ/);
      assert.equal(await page.locator('input,textarea').count(), 0, 'Readonly C');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `C overflow ${width}`);
      await page.screenshot({ path: path.join(output, `sources-${width}.png`), fullPage: true });
      for (const state of ['missing', 'stale', 'current']) {
        await page.locator('#source-state').selectOption(state);
        if (state !== 'current') assert.match(await page.locator('#view').innerText(), /не проверен по источнику/);
        assert.equal(await page.locator('ol li').count(), 3, 'Ordered full answer options');
      }
      await page.locator('[data-nav="tasks"]').click();
      assert.equal(await page.evaluate(() => document.activeElement.id), 'main', 'Navigation focuses content');
      await page.locator('[data-filter="all"]').click();
      await page.locator('[data-task="generation"]').click();
      await page.locator('[data-action="generation"]').click();
      assert.match(await page.locator('#view').innerText(), /GEN-024/);
      assert.match(await page.locator('#view').innerText(), /A0/);
      await page.locator('[data-nav="tasks"]').click();
      await page.locator('[data-task="overdue"]').click();
      await page.locator('[data-action="overdue"]').click();
      assert.match(await page.locator('#view').innerText(), /30 октября 2026/);
      await page.locator('[data-journal]').click();
      assert.match(await page.locator('#view').innerText(), /экспорт|выгруз|пакет/i);
      await page.locator('[data-nav="tasks"]').click();
      for (const state of ['empty', 'filtered-empty', 'loading', 'unavailable', 'error']) {
        await page.locator('#fixture').selectOption(state);
        assert.equal(await page.locator('[data-task]').count(), 0, `${state} must not show stale task rows`);
        await page.locator('[data-list]').click();
        assert.equal(await page.evaluate(() => document.activeElement.getAttribute('data-filter')), 'all', 'Empty return focus');
      }
      await page.locator('#fixture').selectOption('partial');
      assert.equal(await page.locator('[data-task]').count(), 3);
      assert.equal(await page.locator('[data-action]').count(), 0, 'No action on unavailable detail');
      await page.locator('#fixture').selectOption('ready');
      await page.keyboard.press('Tab');
      assert(await page.evaluate(() => document.activeElement !== document.body), 'Keyboard focus retained');
      await page.addStyleTag({ content: 'html { font-size: 200%; }' });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Text resize overflow ${width}`);
      assert.deepEqual(errors, []);
      assert.equal(requests, 0, 'No network attempted');
      results.push({ width, passed: true, requests, pageErrors: errors });
      await context.close();
    }
    console.log(JSON.stringify({ result: 'PASS', results }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
