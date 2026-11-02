import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/** Root starts the exact local candidate; never auto-start or use a live backend. */
export default defineConfig({
  ...base,
  testMatch: /(?:workspace-visual|learning-workspace-ux)\.spec\.ts$/,
  workers: 1,
  webServer: undefined,
  use: {
    ...base.use,
    baseURL: 'http://127.0.0.1:3026',
    serviceWorkers: 'block',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : undefined,
  },
});
