import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * auto-sec onboarding gate smoke — a signed-in operator who belongs to NO
 * workspace must create or join one before reaching the command center, and is
 * shown that gate ONLY on the first login (never again once onboarded).
 *
 * Idempotent: beforeAll resets a dedicated throwaway user to a fresh, verified,
 * workspace-less, un-onboarded state via the live api pod, so the run is
 * repeatable. Never touches the demo logins.
 */
const EMAIL = 'onboard-test@qa.autosec.local';
const PASSWORD = 'OnboardPass123!';

const resetOnboardingUser = () => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'onboardtest'})`,
      "u.username='onboardtest'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=False",
      `u.set_password('${PASSWORD}'); u.save()`,
      'WorkspaceMembership.objects.filter(user=u).delete()',
      'Workspace.objects.filter(workspace_owner=u).delete()',
      "print('reset-ok')"
    ].join('; ')
  );
};

/** Count the user's workspace memberships in the live DB. Guards the
 *  "no duplicate auto-named bootstrap workspace" fix — a create must yield 1. */
const workspaceCount = (): number => {
  const py =
    'from infrastructure.persistence.users.models import CustomUser;' +
    'from infrastructure.persistence.workspaces.models import WorkspaceMembership;' +
    `u=CustomUser.objects.get(email='${EMAIL}');` +
    "print('WSCOUNT=%d' % WorkspaceMembership.objects.filter(user=u).count())";
  const m = sh(py).match(/WSCOUNT=(\d+)/);
  return m ? Number(m[1]) : -1;
};

const login = async (page: Page, email: string, password: string) => {
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
};

test.describe.serial('onboarding gate', () => {
  test.beforeAll(() => {
    resetOnboardingUser();
  });

  test('first login gates to onboarding; create workspace enters the HUD; re-login skips it', async ({
    page
  }) => {
    // First login → HUD, with the onboarding gate as a blocking overlay over it
    // (single-screen rule — not a separate route). The gate is a guided
    // HudFormStepper flow now: Create → Teams → Start (no CREATE/JOIN tabs).
    await page.goto('/identity/login');
    await login(page, EMAIL, PASSWORD);
    await expect(page).toHaveURL(HUD_ROOT_RE);

    // The onboarding overlay: heading + workspace-name input.
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeVisible();
    const wsName = page.getByPlaceholder(/Workspace name/i);
    await expect(wsName).toBeVisible();

    // Stage 1 — Create: name the workspace.
    await wsName.fill('Sentinel SOC');
    await page.getByRole('button', { name: 'CREATE WORKSPACE' }).click();

    // Stage 2 — Teams orientation (Blue/Red seeded per ADR 0007) → CONTINUE.
    const cont = page.getByRole('button', { name: 'CONTINUE', exact: true });
    await expect(cont).toBeVisible();

    // Regression guard: exactly ONE workspace — no spurious auto-named second
    // one minted by the bootstrap during post-create hydration.
    expect(workspaceCount()).toBe(1);

    await cont.click();

    // Stage 3 — Start: enter the command center (full reload onto the HUD).
    await page.getByRole('button', { name: 'ENTER COMMAND CENTER' }).click();
    await expect(page).toHaveURL(HUD_ROOT_RE);
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeHidden();

    // Sign out, then log back in — onboarding must NOT show again.
    await page.getByRole('button', { name: /SIGN OUT/i }).click();
    await expect(page).toHaveURL(/\/identity\/login$/);
    await login(page, EMAIL, PASSWORD);
    await expect(page).toHaveURL(HUD_ROOT_RE);
    // The onboarding overlay must NOT reappear (already onboarded).
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeHidden();
  });
});
