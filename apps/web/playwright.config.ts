import { defineConfig, devices, PlaywrightTestConfig } from '@playwright/test';

/**
 * Playwright E2E config for Kamilya LMS Next.js 14 (App Router).
 * Run against http://localhost:3000 — start with `npm run dev`.
 */
const config: PlaywrightTestConfig = {
  testDir: './tests/e2e',
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    cwd: '<rootDir>',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
};

export default config;
