import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/** Isolated synthetic UX acceptance; never starts a server or uses live APIs. */
export default defineConfig({
  ...base,
  testMatch: /learning-workspace-ux\.spec\.ts$/,
  workers: 1,
  webServer: undefined,
  use: {
    ...base.use,
    baseURL: 'http://127.0.0.1:3024',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : undefined,
  },
});
