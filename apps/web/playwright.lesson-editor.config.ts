import { defineConfig } from '@playwright/test';
import { readFileSync } from 'node:fs';
import base from './playwright.config';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) throw new Error('Use the root-owned built loopback app with PLAYWRIGHT_SKIP_WEBSERVER=1.');
const apiUrl = JSON.parse(readFileSync('.next/required-server-files.json', 'utf8')).config.env.NEXT_PUBLIC_API_URL;
if (!['https://kamilya-lms-api.onrender.com/api', 'https://api.kml.kz/api'].includes(apiUrl)) throw new Error('Build the app with an explicit canonical NEXT_PUBLIC_API_URL before browser QA.');

export default defineConfig({
  ...base, testMatch: /(visual-lesson-editor|author-read-recovery|learning-workspace-ux)\.spec\.ts$/,
  workers: 1, retries: 0, reporter: 'list', webServer: undefined,
  outputDir: '../../.release-evidence/visual-editor113-20261115/browser',
  use: { ...base.use, baseURL: 'http://127.0.0.1:3024', channel: 'chrome' },
});
