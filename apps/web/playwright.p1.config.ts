import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testMatch: /(frontend-p[12]|learning-workspace-ux)\.spec\.ts$/,
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: '../../.release-evidence/frontend-p2-20261110/browser',
  webServer: undefined,
});
