import { test, expect, Page } from '@playwright/test';

/**
 * auto-sec auth lifecycle smoke — the HUD auth gate on /identity/login.
 *
 * Covers what we verified by hand while building it, now automated so it's a
 * regression net as the auth surface grows:
 *   - auth guard bounces an unauthenticated visitor to /identity/login
 *   - password field masks by DEFAULT (never plaintext — the anti-pattern we fixed)
 *   - password login → HUD → sign out → back to login
 *   - register (+ terms gate) → success notice
 *   - forgot-password (reset request) → confirmation
 *   - a wrong password does NOT authenticate (stays on the login route)
 *
 * Assumes the auto-sec stack is up (:8020) with a verified admin from boot and
 * the frontend dev server on :3001.
 */
const ADMIN_EMAIL = process.env.QA_ADMIN_EMAIL || 'admin@octopus.local';
const ADMIN_PASSWORD = process.env.QA_ADMIN_PASSWORD || 'octopus-admin-local';

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
    await fillLogin(page, ADMIN_EMAIL, 'definitely-the-wrong-password');
    // Stays on the login route (no token issued).
    await expect(page).toHaveURL(/\/identity\/login$/);
  });

  test('login → HUD → sign out → login', async ({ page }) => {
    await gotoLogin(page);
    await fillLogin(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    // Lands on the command center.
    await expect(page).toHaveURL(/localhost:3001\/$/);
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
    const email = `qa+${Date.now()}@octopus.local`;
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
  });

  test('forgot password sends a reset link confirmation', async ({ page }) => {
    await gotoLogin(page);
    await page.getByRole('button', { name: 'Forgot password?' }).click();
    await page
      .getByRole('textbox', { name: 'Email' })
      .fill(`qa+${Date.now()}@octopus.local`);
    await page.getByRole('button', { name: /SEND RESET LINK/i }).click();
    await expect(page.getByText(/reset link is on its way/i)).toBeVisible();
  });
});
