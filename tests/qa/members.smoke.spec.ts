import { test, expect, Page } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * Members & access smoke — Settings ▸ Workspace ▸ Members: roster, role change,
 * the permission matrix (direct grants), and inviting an operator.
 *
 * Provisions an owner + two members (member, viewer) in a dedicated workspace,
 * then drives the HUD and verifies role/permission writes landed in the DB.
 */
const OWNER = 'members-e2e@octopus.local';
const PASSWORD = 'MembersPass123!';
const M1 = 'members-e2e-analyst@octopus.local';
const M2 = 'members-e2e-viewer@octopus.local';
const CONTAINER = process.env.QA_WEB_CONTAINER || 'auto_sec-web-1';

const sh = (py: string): string =>
  execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`
  ).toString();

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(OWNER);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(/localhost:3001\/$/);
}

async function openMembers(page: Page) {
  // Deep-link straight to Settings ▸ Members (?section= added for determinism).
  await page.goto('/?panel=settings&section=members');
  await expect(page.getByText('Priya', { exact: false })).toBeVisible({
    timeout: 20_000
  });
}

test.beforeAll(() => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser, UserProfile',
      'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
      `o,_=CustomUser.objects.get_or_create(email='${OWNER}', defaults={'username':'memberse2e'})`,
      "o.username='memberse2e'; o.is_verified=True; o.is_active=True; o.is_onboard_complete=True",
      `o.set_password('${PASSWORD}'); o.save()`,
      "ws=Workspace.objects.all_objects().filter(workspace_owner=o).first() or Workspace.objects.create(workspace_name='Members E2E Org', workspace_type='teamspace', workspace_owner=o, status='active', is_active=True)",
      "UserProfile.objects.update_or_create(user=o, defaults={'active_workspace_id': ws.id})",
      "WorkspaceMembership.objects.get_or_create(workspace=ws, user=o, defaults={'role':'owner','status':'active'})",
      `a,_=CustomUser.objects.get_or_create(email='${M1}', defaults={'username':'m1e2e','first_name':'Priya','last_name':'Nardo'})`,
      `v,_=CustomUser.objects.get_or_create(email='${M2}', defaults={'username':'m2e2e','first_name':'Kwame','last_name':'Osei'})`,
      "WorkspaceMembership.objects.get_or_create(workspace=ws, user=a, defaults={'role':'member','status':'active'})",
      "WorkspaceMembership.objects.get_or_create(workspace=ws, user=v, defaults={'role':'viewer','status':'active'})",
      "print('ready ' + str(ws.id) + ' ' + str(a.id))"
    ].join('; ')
  );
});

test('roster lists owner + members with the owner badge', async ({ page }) => {
  await login(page);
  await openMembers(page);

  await expect(page.getByText('OWNER', { exact: true })).toBeVisible();
  await expect(page.getByText('Priya Nardo')).toBeVisible();
  await expect(page.getByText('Kwame Osei')).toBeVisible();
});

test('changing a member role shows confirmation', async ({ page }) => {
  await login(page);
  await openMembers(page);

  // First member role select (owner has no select — it's an OWNER badge).
  const roleSelect = page
    .locator('select:has(option[value="viewer"])')
    .first();
  await roleSelect.selectOption('viewer');
  await expect(page.getByText('Role updated')).toBeVisible();
});

test('toggling a permission persists a direct grant', async ({ page }) => {
  // Start from a clean grant state so the first-checkbox toggle deterministically
  // GRANTS (an idempotency-safe re-run would otherwise revoke a leftover grant
  // and drop the count to 0). The first matrix cell is manage_settings for the
  // analyst — never role-inherited for a member/viewer, so it's editable.
  sh(
    [
      'from infrastructure.persistence.workspaces.models import WorkspacePermissionGrant',
      'from infrastructure.persistence.users.models import CustomUser',
      `a=CustomUser.objects.get(email='${M1}')`,
      'WorkspacePermissionGrant.objects.filter(user_id=a.id).delete()',
      "print('cleared')"
    ].join('; ')
  );

  await login(page);
  await openMembers(page);

  // Switch to the matrix and grant the first editable capability.
  await page.getByRole('tab', { name: /PERMISSIONS/ }).click();
  const box = page.getByRole('checkbox').first();
  await expect(box).toBeVisible();
  // Await the bulk-grant POST so the DB assertion isn't racing the write.
  const [grantResp] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes('/permissions/bulk') &&
        r.request().method() === 'POST'
    ),
    box.dispatchEvent('click')
  ]);
  expect(grantResp.ok()).toBeTruthy();

  // A grant row must now exist for the analyst.
  const out = sh(
    [
      'from infrastructure.persistence.workspaces.models import WorkspacePermissionGrant, Workspace',
      "from infrastructure.persistence.users.models import CustomUser",
      `a=CustomUser.objects.get(email='${M1}')`,
      "print('GRANTS=' + str(WorkspacePermissionGrant.objects.filter(user_id=a.id).count()))"
    ].join('; ')
  );
  expect(out).toMatch(/GRANTS=[1-9]/);
});

test('inviting an operator surfaces a pending invite', async ({ page }) => {
  await login(page);
  await openMembers(page);

  await page.getByRole('tab', { name: /INVITES/ }).click();
  const email = `invitee+${Date.now().toString().slice(-6)}@octopus.local`;
  await page.getByPlaceholder('operator@org.com').fill(email);
  await page.getByRole('button', { name: /Invite/ }).dispatchEvent('click');

  await expect(page.getByText(/Invite sent/)).toBeVisible();
});
