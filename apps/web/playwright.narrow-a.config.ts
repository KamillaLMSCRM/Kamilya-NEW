import { defineConfig } from '@playwright/test';
import base from './playwright.config';

/** Isolated synthetic acceptance for the Narrow A candidate on loopback3027. */
export default defineConfig({
  ...base,
  testMatch: /narrow-a-visual\.spec\.ts$/,
  workers: 1,
  webServer: undefined,
  use: {
    ...base.use,
    baseURL: 'http://127.0.0.1:3027',
    serviceWorkers: 'block',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : undefined,
  },
});
