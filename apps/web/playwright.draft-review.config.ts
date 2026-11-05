import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base, testMatch: /editorial-draft\.spec\.ts$/, workers: 1, retries: 0,
  webServer: undefined, outputDir: '../../.release-evidence/p30-external-review-20261105/browser',
  use: { ...base.use, baseURL: 'http://127.0.0.1:3026',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : undefined },
});
