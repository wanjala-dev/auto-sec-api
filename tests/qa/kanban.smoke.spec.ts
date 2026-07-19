import { test, expect, Page } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * Kanban / boards smoke — the SOC triage board across the full stack:
 * team → project → column → task, plus the Team↔Project board switcher and the
 * in-place add-column / add-task write paths.
 *
 * Provisions a self-contained org (its own owner, team, project, columns, a
 * seeded finding) via the Django shell, then drives the HUD and verifies writes
 * landed in the DB. Idempotent: get_or_create everywhere; safe to re-run.
 */
const EMAIL = 'kanban-e2e@octopus.local';
const PASSWORD = 'KanbanPass123!';
const CONTAINER = process.env.QA_WEB_CONTAINER || 'auto_sec-web-1';

const sh = (py: string): string =>
  execSync(
    `docker exec ${CONTAINER} python manage.py shell -c "${py}"`
  ).toString();

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(/localhost:3001\/$/);
}

async function openKanban(page: Page) {
  await page.getByRole('button', { name: 'KANBAN', exact: true }).click();
  // The board's default lanes prove the flyout mounted + workspace resolved.
  await expect(page.getByText('SOC TRIAGE BOARD')).toBeVisible();
}

test.beforeAll(() => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser, UserProfile',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from infrastructure.persistence.team.models import Team',
      'from infrastructure.persistence.project.models import Project, Column, Task',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'kanbane2e'})`,
      "u.username='kanbane2e'; u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      `u.set_password('${PASSWORD}'); u.save()`,
      "ws=Workspace.objects.all_objects().filter(workspace_owner=u).first() or Workspace.objects.create(workspace_name='SOC E2E Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True)",
      "UserProfile.objects.update_or_create(user=u, defaults={'active_workspace_id': ws.id})",
      "t=Team.objects.filter(workspace=ws, title='SOC E2E').first() or Team.objects.create(workspace=ws, title='SOC E2E', status='active', created_by=u)",
      't.members.add(u)',
      "c1=Column.objects.get_or_create(team=t, workspace=ws, project=None, title='To Do', defaults={'order':0,'created_by':u})[0]",
      "Column.objects.get_or_create(team=t, workspace=ws, project=None, title='Doing', defaults={'order':1,'created_by':u})",
      "p=Project.objects.filter(workspace=ws, team=t, title='Hunt E2E').first() or Project.objects.create(workspace=ws, team=t, title='Hunt E2E', created_by=u, lead=u)",
      "Column.objects.get_or_create(team=t, workspace=ws, project=p, title='Hypotheses', defaults={'order':0,'created_by':u})",
      "Column.objects.get_or_create(team=t, workspace=ws, project=p, title='Confirmed', defaults={'order':1,'created_by':u})",
      "Task.objects.get_or_create(team=t, workspace=ws, title='[HIGH] E2E finding alpha', defaults={'column':c1,'created_by':u,'source_type':'ai.detection'})",
      "print('ready')"
    ].join('; ')
  );
});

test('team board renders columns + seeded finding', async ({ page }) => {
  await login(page);
  await openKanban(page);

  // Team default board: project-less columns + the seeded task.
  await expect(page.getByText('To Do', { exact: true })).toBeVisible();
  await expect(page.getByText('Doing', { exact: true })).toBeVisible();
  await expect(
    page.getByText('[HIGH] E2E finding alpha')
  ).toBeVisible();
});

test('switching to a project board swaps in the project columns', async ({
  page
}) => {
  await login(page);
  await openKanban(page);

  // The BOARD (project) switcher lists "Team board" + each project.
  await page
    .locator('select:has(option:text("Hunt E2E"))')
    .selectOption({ label: 'Hunt E2E' });

  await expect(page.getByText('Hypotheses', { exact: true })).toBeVisible();
  await expect(page.getByText('Confirmed', { exact: true })).toBeVisible();
  // The team board's lane must NOT be present on the project board.
  await expect(page.getByText('Doing', { exact: true })).toHaveCount(0);
});

test('add-column persists a new lane', async ({ page }) => {
  await login(page);
  await openKanban(page);

  const title = `Escalated ${Date.now().toString().slice(-5)}`;
  // The board renders inside the nav flyout's stacking context — the Test
  // runner's hit-test reads the flyout wrapper as an interceptor even though a
  // real click reaches the button (verified via CDP). dispatchEvent fires the
  // handler directly, which is what we're actually asserting on.
  await page
    .getByRole('button', { name: '+ Add Column' })
    .dispatchEvent('click');
  await page.getByPlaceholder('Column title…').fill(title);
  // Await the create POST so the DB assertion below isn't racing the write
  // (removes the retry-only flake).
  const [createResp] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes('/project/columns/') &&
        r.request().method() === 'POST'
    ),
    page.getByPlaceholder('Column title…').press('Enter')
  ]);
  expect(createResp.ok()).toBeTruthy();

  await expect(page.getByText(title, { exact: true })).toBeVisible();

  const out = sh(
    [
      'from infrastructure.persistence.project.models import Column',
      `print('COL=' + str(Column.objects.filter(title='${title}').exists()))`
    ].join('; ')
  );
  expect(out).toContain('COL=True');
});

test('add-task persists a finding into a lane', async ({ page }) => {
  await login(page);
  await openKanban(page);

  const title = `E2E task beta ${Date.now().toString().slice(-5)}`;
  await page
    .getByRole('button', { name: '+ ADD TASK' })
    .first()
    .dispatchEvent('click');
  await page.getByPlaceholder('New finding…').first().fill(title);
  await page.getByPlaceholder('New finding…').first().press('Enter');

  await expect(page.getByText(title)).toBeVisible();

  const out = sh(
    [
      'from infrastructure.persistence.project.models import Task',
      `print('TASK=' + str(Task.objects.filter(title='${title}').exists()))`
    ].join('; ')
  );
  expect(out).toContain('TASK=True');
});
