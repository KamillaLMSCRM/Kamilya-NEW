import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/** Root starts the exact local candidate on loopback 3024; never auto-start or use a live API. */
export default defineConfig({
  ...base,
  testMatch: /methodologist-guide-captures\.spec\.ts$/,
  workers: 1,
  webServer: undefined,
  use: {
    ...base.use,
    baseURL: 'http://127.0.0.1:3024',
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : undefined,
  },
});
