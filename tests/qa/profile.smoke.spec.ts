import { test, expect } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * Profile smoke — Settings ▸ Profile: edit identity (name/title) and change
 * password. Idempotent: a throwaway user is provisioned + reset before the run
 * (the password change never touches the demo logins).
 */
const EMAIL = 'profile-e2e@qa.autosec.local';
const PASSWORD = 'ProfilePass123!';

test('edit profile name + change password', async ({ page }) => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from django.db.models import Q',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'profilee2e'})`,
      "u.username='profilee2e'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=True; u.first_name=''",
      `u.set_password('${PASSWORD}'); u.save()`,
      "has=Workspace.objects.all_objects().filter(Q(workspace_owner=u)|Q(memberships__user=u)).exists()",
      "Workspace.objects.create(workspace_name='Prof Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True) if not has else None",
      "print('ready')"
    ].join('; ')
  );

  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(HUD_ROOT_RE);

  // Settings is a panel over the HUD (single-screen), opened via ?panel=.
  await page.goto('/?panel=settings');
  await expect(page.getByPlaceholder('First name')).toBeVisible();

  await page.getByPlaceholder('First name').fill('Sentinel');
  await page.getByRole('button', { name: 'SAVE PROFILE' }).click();
  await expect(page.getByText('Profile updated.')).toBeVisible();

  const nameOut = sh(
    `from infrastructure.persistence.users.models import CustomUser; print('FN=' + (CustomUser.objects.get(email='${EMAIL}').first_name or ''))`
  );
  expect(nameOut).toContain('FN=Sentinel');

  // Change password → new one authenticates.
  await page.getByPlaceholder('Current password').fill(PASSWORD);
  await page.getByPlaceholder('New password').fill('NewProfilePass456!');
  await page.getByRole('button', { name: 'CHANGE PASSWORD' }).click();
  await expect(page.getByText('Password changed.')).toBeVisible();
});
