import { test, expect, Page } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * auto-sec onboarding gate smoke — a signed-in operator who belongs to NO
 * workspace must create or join one before reaching the command center, and is
 * shown that gate ONLY on the first login (never again once onboarded).
 *
 * Idempotent: beforeAll resets a dedicated user to a fresh, verified,
 * workspace-less, un-onboarded state via the running container, so the run is
 * repeatable. Requires the auto-sec stack (:8020) + frontend (:3001).
 */
const EMAIL = 'onboard-test@octopus.local';
const PASSWORD = 'OnboardPass123!';
const CONTAINER = process.env.QA_WEB_CONTAINER || 'octopus_security-web-1';

const resetOnboardingUser = () => {
  const py = [
    'from infrastructure.persistence.users.models import CustomUser',
    'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
    `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'onboardtest'})`,
    "u.username='onboardtest'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=False",
    `u.set_password('${PASSWORD}'); u.save()`,
    'WorkspaceMembership.objects.filter(user=u).delete()',
    'Workspace.objects.filter(workspace_owner=u).delete()',
    "print('reset-ok')"
  ].join('; ');
  execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`,
    { stdio: 'ignore' }
  );
};

/** Count the user's workspace memberships in the running container. Guards the
 *  "no duplicate auto-named bootstrap workspace" fix — a create must yield 1. */
const workspaceCount = (): number => {
  const py =
    "from infrastructure.persistence.users.models import CustomUser;" +
    'from infrastructure.persistence.workspaces.models import WorkspaceMembership;' +
    `u=CustomUser.objects.get(email='${EMAIL}');` +
    "print('WSCOUNT=%d' % WorkspaceMembership.objects.filter(user=u).count())";
  const out = execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`
  ).toString();
  const m = out.match(/WSCOUNT=(\d+)/);
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
    // First login → HUD, with the onboarding gate as a blocking MODAL over it
    // (single-screen rule — not a separate route).
    await page.goto('/identity/login');
    await login(page, EMAIL, PASSWORD);
    await expect(page).toHaveURL(/localhost:3001\/$/);

    // The onboarding modal: stepper + create/join tabs.
    await expect(page.getByText(/STEP 1 \/ 2/)).toBeVisible();
    await expect(page.getByRole('tab', { name: 'CREATE' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'JOIN' })).toBeVisible();

    // Create a workspace → lands in the command center.
    await page
      .getByRole('textbox', { name: /Workspace name/i })
      .fill('Sentinel SOC');
    await page.getByRole('button', { name: 'CREATE WORKSPACE' }).click();
    await expect(page).toHaveURL(/localhost:3001\/$/);

    // Regression guard: exactly ONE workspace — no spurious auto-named second
    // one minted by the bootstrap during post-create hydration.
    expect(workspaceCount()).toBe(1);

    // Sign out, then log back in — onboarding must NOT show again.
    await page.getByRole('button', { name: /SIGN OUT/i }).click();
    await expect(page).toHaveURL(/\/identity\/login$/);
    await login(page, EMAIL, PASSWORD);
    await expect(page).toHaveURL(/localhost:3001\/$/);
    // The onboarding modal must NOT reappear (already onboarded).
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeHidden();
  });
});
