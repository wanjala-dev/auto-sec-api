import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { E2E, HUD_ROOT_RE } from './helpers/env';

/**
 * auto-sec auth lifecycle smoke — the HUD auth gate on /identity/login.
 *
 * Covers what we verified by hand while building it, now automated so it's a
 * regression net as the auth surface grows:
 *   - auth guard bounces an unauthenticated visitor to /identity/login
 *   - password field masks by DEFAULT (never plaintext — the anti-pattern we fixed)
 *   - password login → HUD → sign out → back to login (demo admin, read-only)
 *   - register (+ terms gate) → success notice (throwaway user, cleaned after)
 *   - forgot-password (reset request) → confirmation
 *   - a wrong password does NOT authenticate (throwaway user — never the demo
 *     admin, so repeated failed attempts can't trip the lockout policy on it)
 *
 * Requires the live k8s stack + the frontend dev server (see playwright.config).
 */
const THROWAWAY_EMAIL = 'auth-e2e@qa.autosec.local';
const THROWAWAY_PASSWORD = 'AuthE2ePass123!';

const gotoLogin = async (page: Page) => {
  await page.goto('/identity/login');
  await expect(page.getByRole('tab', { name: 'SIGN IN' })).toBeVisible();
};

const fillLogin = async (page: Page, email: string, password: string) => {
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
};

test.describe('auth lifecycle', () => {
  test.beforeAll(() => {
    // Throwaway fixture for the wrong-password probe — verified + onboarded so
    // a correct-credential control login would land on the HUD, but we never
    // point failed attempts at the demo admin.
    sh(
      [
        'from infrastructure.persistence.users.models import CustomUser',
        `u,_=CustomUser.objects.get_or_create(email='${THROWAWAY_EMAIL}', defaults={'username':'authe2e'})`,
        "u.username='authe2e'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
        `u.set_password('${THROWAWAY_PASSWORD}'); u.save()`,
        "print('ready')",
      ].join('; ')
    );
  });

  test('auth guard redirects an unauthenticated visitor to the login', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/identity\/login$/);
    await expect(page.getByText('AUTO-SEC')).toBeVisible();
  });

  test('password is masked by default (never plaintext)', async ({ page }) => {
    await gotoLogin(page);
    const pw = page.getByRole('textbox', { name: 'Password' });
    await pw.fill('SuperSecret123');
    // The anti-pattern we fixed: type must be "password", not "text".
    await expect(pw).toHaveAttribute('type', 'password');
  });

  test('wrong password does not authenticate', async ({ page }) => {
    await gotoLogin(page);
    await fillLogin(page, THROWAWAY_EMAIL, 'definitely-the-wrong-password');
    // Stays on the login route (no token issued).
    await expect(page).toHaveURL(/\/identity\/login$/);
  });

  test('login → HUD → sign out → login', async ({ page }) => {
    await gotoLogin(page);
    await fillLogin(page, E2E.email, E2E.password);
    // Lands on the command center.
    await expect(page).toHaveURL(HUD_ROOT_RE);
    await expect(page.getByText('AUTO-SEC').first()).toBeVisible();
    // Sign out returns to the login gate.
    await page.getByRole('button', { name: /SIGN OUT/i }).click();
    await expect(page).toHaveURL(/\/identity\/login$/);
  });

  test('register (+ terms gate) shows the verify-email notice', async ({
    page,
  }) => {
    await gotoLogin(page);
    await page.getByRole('tab', { name: 'REGISTER' }).click();
    const email = `qa-register+${Date.now()}@qa.autosec.local`;
    await page.getByRole('textbox', { name: 'Full name' }).fill('QA Operator');
    await page.getByRole('textbox', { name: 'Email' }).fill(email);
    await page.getByRole('textbox', { name: 'Password' }).fill('QaSecurePass123!');

    // Terms gate: CREATE ACCOUNT is disabled until the box is checked.
    const create = page.getByRole('button', { name: 'CREATE ACCOUNT' });
    await expect(create).toBeDisabled();
    await page.getByRole('button', { name: /I agree to the Terms/i }).click();
    await expect(create).toBeEnabled();
    await create.click();

    // Success renders in BOTH an inline notice and a toast — scope to the first.
    await expect(page.getByText(/Account created\./i).first()).toBeVisible();

    // Clean the throwaway registration back out of the live DB.
    sh(
      [
        'from infrastructure.persistence.users.models import CustomUser',
        `CustomUser.objects.filter(email='${email}').delete()`,
        "print('cleaned')",
      ].join('; ')
    );
  });

  test('forgot password sends a reset link confirmation', async ({ page }) => {
    await gotoLogin(page);
    await page.getByRole('button', { name: 'Forgot password?' }).click();
    await page
      .getByRole('textbox', { name: 'Email' })
      .fill(`qa-reset+${Date.now()}@qa.autosec.local`);
    await page.getByRole('button', { name: /SEND RESET LINK/i }).click();
    await expect(page.getByText(/reset link is on its way/i)).toBeVisible();
  });
});
