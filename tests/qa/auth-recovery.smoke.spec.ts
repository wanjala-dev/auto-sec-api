import { test, expect } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * auth recovery smoke — the pages reached from email links:
 *   - password reset-confirm (/identity/password-reset-confirm/<uid>/<token>/)
 *   - email confirmation (/identity/email-confirmed?token=…)
 *
 * Idempotent: each test provisions its own user and mints a REAL token via the
 * running container (the glue that replaces reading an inbox — the product path
 * is still exercised). Requires the auto-sec stack (:8020) + frontend (:3001).
 */
const CONTAINER = process.env.QA_WEB_CONTAINER || 'octopus_security-web-1';
const sh = (py: string): string =>
  execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`
  ).toString();

test('password reset-confirm: token → new password → success → new password logs in', async ({
  page
}) => {
  const email = 'reset-e2e@octopus.local';
  const py = [
    'from infrastructure.persistence.users.models import CustomUser',
    'from django.utils.http import urlsafe_base64_encode',
    'from django.utils.encoding import force_bytes',
    'from django.contrib.auth.tokens import PasswordResetTokenGenerator',
    `u,_=CustomUser.objects.get_or_create(email='${email}', defaults={'username':'resete2e'})`,
    "u.username='resete2e'; u.is_verified=True; u.is_active=True",
    "u.set_password('InitialPass123!'); u.save()",
    'uid=urlsafe_base64_encode(force_bytes(u.id))',
    'tok=PasswordResetTokenGenerator().make_token(u)',
    "print('URL=/identity/password-reset-confirm/%s/%s/' % (uid, tok))"
  ].join('; ');
  const url = sh(py).match(/URL=(\S+)/)![1];

  await page.goto(url);
  const newPw = 'BrandNewPass789!';
  await page.getByPlaceholder('New password', { exact: true }).fill(newPw);
  await page
    .getByPlaceholder('Confirm new password', { exact: true })
    .fill(newPw);
  await page.getByRole('button', { name: 'UPDATE PASSWORD' }).click();
  await expect(page).toHaveURL(/\/identity\/reset-password-success$/);

  // The new password authenticates (lands on onboarding or the HUD — not login).
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password' }).fill(newPw);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).not.toHaveURL(/\/identity\/login$/);
});

test('email confirmation: token → verified', async ({ page }) => {
  const email = 'verify-e2e@octopus.local';
  const py = [
    'from infrastructure.persistence.users.models import CustomUser',
    'from rest_framework_simplejwt.tokens import RefreshToken',
    `u,_=CustomUser.objects.get_or_create(email='${email}', defaults={'username':'verifye2e'})`,
    "u.username='verifye2e'; u.is_verified=False; u.is_active=True; u.save()",
    "print('TOKEN=%s' % RefreshToken.for_user(u).access_token)"
  ].join('; ');
  const token = sh(py).match(/TOKEN=(\S+)/)![1];

  await page.goto(`/identity/email-confirmed?token=${token}`);
  await expect(page.getByText('EMAIL VERIFIED')).toBeVisible();

  const verified = sh(
    `from infrastructure.persistence.users.models import CustomUser; print('V=%s' % CustomUser.objects.get(email='${email}').is_verified)`
  );
  expect(verified).toContain('V=True');
});
