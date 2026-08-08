import { test, expect } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * Sessions smoke — Settings ▸ Sessions. Lists the operator's active sessions
 * (current one flagged THIS DEVICE) and signs out all others. Throwaway user —
 * never revokes the demo logins' sessions.
 */
const EMAIL = 'sessions-e2e@qa.autosec.local';
const PASSWORD = 'SessPass123!';

test('sessions list + sign out others', async ({ page }) => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from django.db.models import Q',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'sessionse2e'})`,
      "u.username='sessionse2e'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      `u.set_password('${PASSWORD}'); u.save()`,
      "has=Workspace.objects.all_objects().filter(Q(workspace_owner=u)|Q(memberships__user=u)).exists()",
      "Workspace.objects.create(workspace_name='Sess Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True) if not has else None",
      "print('ready')"
    ].join('; ')
  );

  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(HUD_ROOT_RE);

  // Settings is a panel over the HUD (single-screen); open it, then Sessions tab.
  await page.goto('/?panel=settings');
  await page.getByRole('tab', { name: 'SESSIONS' }).click();
  await expect(page.getByText('ACTIVE SESSIONS')).toBeVisible();
  // "THIS DEVICE" renders in both the summary strip and the session row —
  // scope to the first match (strict mode).
  await expect(page.getByText('THIS DEVICE').first()).toBeVisible();

  // If there are other sessions, sign them out; the current one always remains.
  const signOutOthers = page.getByRole('button', { name: 'SIGN OUT OTHERS' });
  if (await signOutOthers.isVisible().catch(() => false)) {
    await signOutOthers.click();
    await expect(signOutOthers).toBeHidden();
  }
  await expect(page.getByText('THIS DEVICE').first()).toBeVisible();
});
