import { test, expect, Page } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * HUD surfaces smoke — the Reports studio (draft create + save; NO live LLM
 * call — generation is deliberately not exercised in e2e to keep the suite
 * deterministic and free), the Workflows panel, and the dark ⇄ light toggle.
 */
const EMAIL = 'surfaces-e2e@octopus.local';
const PASSWORD = 'SurfacesPass123!';
const CONTAINER = process.env.QA_WEB_CONTAINER || 'auto_sec-web-1';

const sh = (py: string): string =>
  execSync(`docker exec ${CONTAINER} python manage.py shell -c "${py}"`).toString();

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(/localhost:3001\/$/);
}

test.beforeAll(() => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser, UserProfile',
      'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'surfacese2e'})`,
      "u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      `u.set_password('${PASSWORD}'); u.save()`,
      "ws=Workspace.objects.all_objects().filter(workspace_owner=u).first() or Workspace.objects.create(workspace_name='Surfaces E2E Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True)",
      "UserProfile.objects.update_or_create(user=u, defaults={'active_workspace_id': ws.id})",
      "WorkspaceMembership.objects.get_or_create(workspace=ws, user=u, defaults={'role':'owner','status':'active'})",
      "print('ready')"
    ].join('; ')
  );
});

test('Reports studio: create draft + edit title + save persists', async ({
  page
}) => {
  await login(page);
  await page.locator('button:has-text("REPORTS")').first().click();
  await expect(
    page.locator('input[placeholder="Ask the agent…"], input[placeholder="Select a report first"]').first()
  ).toBeVisible({ timeout: 20_000 });

  await page.getByRole('button', { name: 'NEW' }).dispatchEvent('click');
  await expect(page.locator('input[placeholder="Report title…"]')).toBeVisible();

  const title = `E2E RCA ${Date.now().toString().slice(-5)}`;
  await page.locator('input[placeholder="Report title…"]').fill(title);
  await page.getByRole('button', { name: 'Save' }).dispatchEvent('click');
  await expect(page.getByText('Draft saved')).toBeVisible();

  const out = sh(
    [
      'from infrastructure.persistence.content.models import WritingDraft',
      `print('DRAFT=' + str(WritingDraft.objects.filter(title='${title}').exists()))`
    ].join('; ')
  );
  expect(out).toContain('DRAFT=True');
});

test('Workflows panel opens with list or empty state', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'WORKFLOWS', exact: true }).click();
  await expect(page.getByText('AUTOMATIONS')).toBeVisible();
});

test('dark ⇄ light toggle flips tokens and persists', async ({ page }) => {
  await login(page);
  await page.locator('button:has-text("LIGHT")').click();
  await expect(page.locator('.hud-light').first()).toBeVisible();
  // Persisted across reload.
  await page.reload();
  await expect(page.locator('.hud-light').first()).toBeVisible();
  // And back to dark.
  await page.locator('button:has-text("DARK")').click();
  await expect(page.locator('.hud-light')).toHaveCount(0);
});
