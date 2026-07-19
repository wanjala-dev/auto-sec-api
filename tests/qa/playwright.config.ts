import { defineConfig, devices } from '@playwright/test';

/**
 * auto-sec E2E QA — Playwright Test runner config.
 *
 * Localhost-only for now: the frontend dev server on :3001 (which talks to the
 * API on :8020). No demo target yet. Specs are added as we build features; the
 * first suite is the auth lifecycle (login / logout / register / reset /
 * password-masking / auth-guard).
 *
 * Prereqs: the auto-sec stack up (`octopus_security-web-1` on :8020) + the
 * frontend dev server on :3001. A verified admin exists from boot
 * (admin@octopus.local); override creds via QA_ADMIN_EMAIL / QA_ADMIN_PASSWORD.
 *
 * Run:
 *   cd tests/qa && npm install && npx playwright install chromium
 *   npx playwright test            # headless
 *   npx playwright test --headed   # watch it drive
 */
const LOCAL = process.env.QA_LOCAL_URL || 'http://localhost:3001';

export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 1,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: LOCAL,
    trace: 'on',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'autosec',
      testMatch: /(auth|onboarding|auth-recovery|twofactor|sessions|profile|kanban|members|collab|surfaces)\.smoke\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], baseURL: LOCAL },
    },
  ],
});
