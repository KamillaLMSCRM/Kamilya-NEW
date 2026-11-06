const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const { pathToFileURL } = require('node:url');
const { chromium, expect } = require('../../../../apps/web/node_modules/@playwright/test');

const output = path.resolve(__dirname, '../../../../.release-evidence/source-editorial-review-20261106');
const isolated = path.join(output, 'isolated');
const standalone = path.join(isolated, 'prototype.html');
fs.mkdirSync(isolated, { recursive: true });
fs.copyFileSync(path.join(__dirname, 'prototype.html'), standalone);

for (const [width, height, name] of [[1440, 960, 'desktop'], [390, 844, 'mobile']]) {
  test(`standalone source review on ${name}`, async () => {
    assert.deepEqual(fs.readdirSync(isolated), ['prototype.html']);
    assert.doesNotMatch(fs.readFileSync(standalone, 'utf8'), /<(?:link|img|iframe|script)\b[^>]*(?:src|href)\s*=/i);
    const browser = await chromium.launch();
    try {
      const context = await browser.newContext({ viewport: { width, height }, offline: true });
      await context.route(/https?:/, route => route.abort());
      const page = await context.newPage();
      const external = [];
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => {
        if (!request.url().startsWith('file:')) external.push(request.url());
      });
      await page.goto(pathToFileURL(standalone).href);
      await expect(page.getByRole('heading', { name: 'Согласование исходника' })).toBeVisible();
      await expect(page.getByText('Открыто: 3', { exact: true })).toBeVisible();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
      await page.screenshot({ path: path.join(output, `${name}.png`), animations: 'disabled' });

      const continueButton = page.getByRole('button', { name: 'К утверждению редакции' });
      const save = page.getByRole('button', { name: 'Сохранить решение' });
      const reason = page.getByRole('textbox', { name: 'Основание решения' });
      await expect(continueButton).toBeDisabled();
      await page.getByRole('button', { name: 'Помощь ИИ' }).click();
      await expect(page.getByText('Пример подсказки ИИ.')).toBeVisible();
      await expect(save).toBeDisabled();
      await page.getByRole('radio', { name: /Внутренний пункт 2/ }).check();
      await reason.fill('Подтверждено автором документа.');
      await save.click();
      await expect(page.getByText('Открыто: 2', { exact: true })).toBeVisible();

      const threshold = page.getByRole('button', { name: /Как обработать сумму ровно/ });
      await threshold.focus();
      await threshold.press('Enter');
      if (width === 390) await expect(page.getByRole('region', { name: 'Детали вопроса' })).toBeFocused();
      await page.getByRole('button', { name: 'Оставить открытым' }).click();
      await expect(continueButton).toBeDisabled();
      await page.getByRole('radio', { name: /Ровно 45 входит в порядок А/ }).check();
      await reason.fill('Автор подтвердил включение границы.');
      await save.click();

      await page.getByRole('button', { name: /Какой документ нужно приложить/ }).click();
      await page.getByRole('radio', { name: 'Своя формулировка' }).check();
      const replacement = 'Приложить копию расходного распоряжения.';
      await page.getByRole('textbox', { name: 'Новый текст фрагмента' }).fill(replacement);
      await reason.fill('Термин подтверждён владельцем.');
      await save.click();

      await page.getByRole('button', { name: 'Автоправки', exact: true }).click();
      await page.getByRole('button', { name: 'Отменить автоправку' }).click();
      await page.getByRole('button', { name: 'Журнал', exact: true }).click();
      await expect(page.getByText('Автоправка отменена', { exact: true })).toBeVisible();
      await expect(page.getByText('Применена автоправка', { exact: true })).toBeVisible();

      await continueButton.click();
      const seal = page.getByRole('button', { name: 'Утвердить эту редакцию' });
      const edition = page.getByRole('region', { name: 'Рабочая редакция' });
      await expect(seal).toBeDisabled();
      await expect(edition).toContainText(replacement);
      await expect(edition).toContainText('Запишите номер в учётной каротчке.');
      await page.getByRole('checkbox', { name: /Я сверил рабочую редакцию/ }).check();
      await seal.click();
      await expect(page.getByRole('heading', { name: 'Рабочая редакция утверждена' })).toBeVisible();
      await page.getByRole('button', { name: 'Перейти к генерации' }).click();
      await expect(page.getByRole('status')).toHaveText(/утверждённую редакцию v6/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
      assert.deepEqual(errors, []);
      assert.deepEqual(external, []);
    } finally {
      await browser.close();
    }
  });
}
