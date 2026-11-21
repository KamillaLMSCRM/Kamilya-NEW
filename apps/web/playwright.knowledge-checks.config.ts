import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';
import base from './playwright.config';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) throw new Error('Use the root-owned built loopback app.');
const apiUrl = JSON.parse(readFileSync('.next/required-server-files.json', 'utf8')).config.env.NEXT_PUBLIC_API_URL;
if (!['https://kamilya-lms-api.onrender.com/api', 'https://api.kml.kz/api'].includes(apiUrl)) throw new Error('Build with an explicit canonical API URL.');

export default defineConfig({
  ...base,
  testMatch: /(knowledge-checks|matching-pairs|learning-workspace-ux)\.spec\.ts$/,
  workers: 1,
  retries: 0,
  reporter: 'list',
  webServer: undefined,
  outputDir: '../../.release-evidence/knowledge-checks114-20261115/browser',
  use: { ...base.use, baseURL: 'http://127.0.0.1:3024', channel: 'chrome' },
});
