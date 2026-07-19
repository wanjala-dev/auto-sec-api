import { test, expect } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * 2FA setup smoke — Settings ▸ Security. Enable via the real QR/verify flow
 * (the live TOTP code is computed from the provisioned device via django_otp in
 * the container — the glue that replaces holding a phone). Idempotent: the user
 * is reset (onboarded, 2FA off) before, and 2FA is torn down after.
 */
const EMAIL = 'twofa-e2e@octopus.local';
const PASSWORD = 'TwoFaPass123!';
const CONTAINER = process.env.QA_WEB_CONTAINER || 'octopus_security-web-1';
const sh = (py: string): string =>
  execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`
  ).toString();

const resetUser = () =>
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
      'from django_otp.plugins.otp_totp.models import TOTPDevice',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'twofae2e'})`,
      "u.username='twofae2e'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      "[setattr(u,f,v) for f,v in [('two_factor_enabled',False),('two_factor_confirmed_at',None)] if hasattr(u,f)]",
      `u.set_password('${PASSWORD}'); u.save()`,
      'TOTPDevice.objects.filter(user=u).delete()',
      // an active workspace so the onboarding gate is satisfied
      'from django.db.models import Q',
      "has=Workspace.objects.all_objects().filter(Q(workspace_owner=u)|Q(memberships__user=u)).exists()",
      "w=Workspace.objects.create(workspace_name='TwoFA Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True) if not has else None",
      "print('reset-ok')"
    ].join('; ')
  );

const liveTotp = (): string => {
  const out = sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from django_otp.plugins.otp_totp.models import TOTPDevice',
      'from django_otp.oath import totp',
      `u=CustomUser.objects.get(email='${EMAIL}')`,
      "d=TOTPDevice.objects.filter(user=u).order_by('-id').first()",
      "print('CODE=%06d' % totp(d.bin_key, step=d.step, t0=d.t0, digits=d.digits))"
    ].join('; ')
  );
  return out.match(/CODE=(\d{6})/)![1];
};

test('enable 2FA end-to-end via the Settings security UI', async ({ page }) => {
  resetUser();

  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(/localhost:3001\/$/);

  // Settings is a panel over the HUD (single-screen); open it, then Security tab.
  await page.goto('/?panel=settings');
  await page.getByRole('tab', { name: 'SECURITY' }).click();
  await expect(page.getByText('TWO-FACTOR AUTHENTICATION')).toBeVisible();
  await expect(page.getByText('DISABLED')).toBeVisible();

  // Start setup → the device is provisioned; the QR + manual secret render.
  await page.getByRole('button', { name: 'ENABLE 2FA' }).click();
  await expect(page.getByText(/enter manually/i)).toBeVisible();

  // Compute the current code from the just-provisioned device and verify.
  await page.getByPlaceholder('123456').fill(liveTotp());
  await page.getByRole('button', { name: 'VERIFY & ENABLE' }).click();

  await expect(page.getByText('ENABLED', { exact: true })).toBeVisible();
});
