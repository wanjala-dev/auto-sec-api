import { defineConfig, devices } from '@playwright/test';

import { E2E } from './helpers/env';

/**
 * auto-sec deep identity/admin QA — Playwright Test runner config.
 *
 * Runs against an ALREADY-RUNNING frontend dev server (default the stable
 * server on :3015) backed by the live local k8s cluster (namespace `autosec`).
 * Backend fixture provisioning goes through `kubectl exec deploy/api` — see
 * helpers/backend.ts.
 *
 * Env contract (all optional; mirrors the frontend e2e/ suite):
 *   E2E_BASE_URL   frontend origin      (default http://localhost:3015)
 *   E2E_EMAIL      admin login email    (default test@autosec.local)
 *   E2E_PASSWORD   admin login password (default AutoSecTest2026!)
 *   QA_KUBE_NS     k8s namespace        (default autosec)
 *   QA_KUBE_TARGET kubectl exec target  (default deploy/api)
 *
 * Run:
 *   cd tests/qa && npm install && npx playwright install chromium
 *   npx playwright test            # headless
 *   npx playwright test --headed   # watch it drive
 */
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
    baseURL: E2E.baseURL,
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
      use: {
        ...devices['Desktop Chrome'],
        baseURL: E2E.baseURL,
        // MobileGate hides the HUD below 1024px wide; give the HUD room.
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
