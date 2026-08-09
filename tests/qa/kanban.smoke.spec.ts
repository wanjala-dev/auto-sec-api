import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * Kanban / boards smoke — the SOC triage board across the full stack:
 * team → project → column → task, plus the Team↔Project board switcher and the
 * in-place add-column / add-task write paths.
 *
 * Provisions a self-contained org (its own throwaway owner, team, project,
 * columns, a seeded finding) via the Django shell in the api pod, then drives
 * the HUD and verifies writes landed in the DB. Idempotent: get_or_create
 * everywhere; safe to re-run. Never touches the demo workspace.
 */
const EMAIL = 'kanban-e2e@qa.autosec.local';
const PASSWORD = 'KanbanPass123!';

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(HUD_ROOT_RE);
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
  const addColumn = page.getByRole('button', { name: '+ Add Column' });
  // The board paints its lanes before the team resolves, so the control is
  // disabled until a create can actually succeed. Waiting on that affordance
  // is the whole point — it replaces the old blind sleep, and it fails loudly
  // if the board ever offers the button while it still can't create.
  await expect(addColumn).toBeEnabled();
  // The board renders inside the nav flyout's stacking context — the Test
  // runner's hit-test reads the flyout wrapper as an interceptor even though a
  // real click reaches the button (verified via CDP). dispatchEvent fires the
  // handler directly, which is what we're actually asserting on.
  await addColumn.dispatchEvent('click');
  const titleInput = page.getByPlaceholder('Column title…');
  await titleInput.pressSequentially(title);
  await expect(titleInput).toHaveValue(title);
  // Enter fires with NO settle: once the board is ready, an Enter straight
  // after typing must create the column. A sleep here would hide a regression.
  // Await the create POST so the DB assertion below isn't racing the write
  // (removes the retry-only flake).
  const [createResp] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes('/project/columns/') &&
        r.request().method() === 'POST'
    ),
    titleInput.press('Enter')
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

/**
 * Simulated pointer drag that satisfies dnd-kit's PointerSensor activation
 * constraint (5px of travel before a drag starts): press, jiggle past the
 * threshold, glide to the target in small steps so onDragOver fires along the
 * way, settle, release.
 */
async function pointerDrag(
  page: Page,
  from: { x: number; y: number },
  to: { x: number; y: number }
) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 8, from.y + 2, { steps: 3 });
  await page.waitForTimeout(150);
  for (let i = 1; i <= 25; i += 1) {
    await page.mouse.move(
      from.x + ((to.x - from.x) * i) / 25,
      from.y + ((to.y - from.y) * i) / 25
    );
    await page.waitForTimeout(40);
  }
  await page.waitForTimeout(500);
  await page.mouse.up();
}

/**
 * The drag-mechanics regressions get their OWN two-lane team board ("DND E2E")
 * so lane geometry stays clean and deterministic — the shared "SOC E2E" board
 * accumulates a column + a task per run of the earlier write-path specs, which
 * makes pixel-level drags flaky. Wiped + re-seeded on every run.
 */
const DND_TEAM = 'DND E2E';

function seedDndBoard(taskTitle: string) {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from infrastructure.persistence.team.models import Team',
      'from infrastructure.persistence.project.models import Column, Task',
      `u=CustomUser.objects.get(email='${EMAIL}')`,
      'ws=Workspace.objects.all_objects().filter(workspace_owner=u).first()',
      `t=Team.objects.filter(workspace=ws, title='${DND_TEAM}').first() or Team.objects.create(workspace=ws, title='${DND_TEAM}', status='active', created_by=u)`,
      't.members.add(u)',
      'Task.objects.filter(team=t).delete()',
      "c1=Column.objects.get_or_create(team=t, workspace=ws, project=None, title='To Do', defaults={'order':0,'created_by':u})[0]",
      "c2=Column.objects.get_or_create(team=t, workspace=ws, project=None, title='Doing', defaults={'order':1,'created_by':u})[0]",
      "c1.order=0; c1.save(update_fields=['order']); c2.order=1; c2.save(update_fields=['order'])",
      `Task.objects.create(team=t, workspace=ws, title='${taskTitle}', column=c1, created_by=u, source_type='ai.detection')`,
      "print('ready')"
    ].join('; ')
  );
}

async function openDndBoard(page: Page) {
  await login(page);
  await openKanban(page);
  await page.locator('select[aria-label="Team"]').selectOption({ label: DND_TEAM });
  await expect(
    page.locator('[data-kanban-lane][data-kanban-lane-title="To Do"]')
  ).toBeVisible();
  await expect(
    page.locator('[data-kanban-lane][data-kanban-lane-title="Doing"]')
  ).toBeVisible();
}

test('dragging a card into an EMPTY lane persists the move', async ({ page }) => {
  // Regression (found 2026-08-09): with bare closestCorners collision
  // detection, a tall empty lane's corners average farther from the drag rect
  // than the dragged card's own vacated slot, so `over` never left the card
  // and dropping into an empty column was a silent no-op — the card snapped
  // back. Fixed in the HUD board with pointer-first collision detection
  // (pointerWithin, closestCorners fallback).
  const title = `E2E empty-lane drag ${Date.now().toString().slice(-5)}`;
  seedDndBoard(title);
  await openDndBoard(page);

  const card = page.locator(`[data-kanban-card]:has-text("${title}")`).first();
  await expect(card).toBeVisible();
  const cardBox = await card.boundingBox();
  const destLane = page.locator('[data-kanban-lane][data-kanban-lane-title="Doing"]');
  const destBox = await destLane.boundingBox();
  if (!cardBox || !destBox) throw new Error('card/lane not measurable');

  await pointerDrag(
    page,
    { x: cardBox.x + cardBox.width / 2, y: cardBox.y + 12 },
    { x: destBox.x + destBox.width / 2, y: destBox.y + 80 }
  );

  // The card lands in the empty lane and the move survives the debounced
  // patch-queue flush + a full reload (server truth, not optimistic state).
  await expect(destLane.locator(`[data-kanban-card]:has-text("${title}")`)).toBeVisible();
  await expect
    .poll(
      () =>
        sh(
          [
            'from infrastructure.persistence.project.models import Task',
            `t=Task.objects.get(title='${title}')`,
            "print('COL=' + t.column.title)"
          ].join('; ')
        ),
      // The patch queue debounces the flush and each request to the local
      // cluster runs ~5s — 15s raced the write and flaked; 45s is safe.
      { timeout: 45_000 }
    )
    .toContain('COL=Doing');

  await page.reload();
  await openKanban(page);
  await page.locator('select[aria-label="Team"]').selectOption({ label: DND_TEAM });
  await expect(
    page
      .locator('[data-kanban-lane][data-kanban-lane-title="Doing"]')
      .locator(`[data-kanban-card]:has-text("${title}")`)
  ).toBeVisible();
});

test('dragging a lane header reorders the board columns and persists', async ({ page }) => {
  // Regression (found 2026-08-09): the backend reorder endpoint
  // (POST /project/columns/reorder/) and the shared drag hook's Column branch
  // both existed, but the HUD board never rendered lanes as sortable — columns
  // simply could not be dragged. Fixed by making each lane header a drag
  // handle inside a horizontal SortableContext.
  seedDndBoard(`E2E reorder anchor ${Date.now().toString().slice(-5)}`);
  await openDndBoard(page);

  const header = (title: string) =>
    page.locator(`[data-kanban-lane-header]:has(:text-is("${title}"))`).first();

  await expect(header('To Do')).toBeVisible();
  const fromBox = await header('To Do').boundingBox();
  const destLane = page.locator('[data-kanban-lane][data-kanban-lane-title="Doing"]');
  const destBox = await destLane.boundingBox();
  if (!fromBox || !destBox) throw new Error('lane headers not measurable');

  const order = () =>
    sh(
      [
        'from infrastructure.persistence.users.models import CustomUser',
        'from infrastructure.persistence.workspaces.models import Workspace',
        'from infrastructure.persistence.team.models import Team',
        'from infrastructure.persistence.project.models import Column',
        `u=CustomUser.objects.get(email='${EMAIL}')`,
        'ws=Workspace.objects.all_objects().filter(workspace_owner=u).first()',
        `t=Team.objects.get(workspace=ws, title='${DND_TEAM}')`,
        "print('ORDER=' + ','.join(Column.objects.filter(team=t, workspace=ws, project__isnull=True).order_by('order').values_list('title', flat=True)))"
      ].join('; ')
    );

  const [reorderResp] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes('/project/columns/reorder/') && r.request().method() === 'POST'
    ),
    pointerDrag(
      page,
      { x: fromBox.x + fromBox.width / 2, y: fromBox.y + fromBox.height / 2 },
      { x: destBox.x + destBox.width / 2, y: fromBox.y + fromBox.height / 2 }
    )
  ]);
  expect(reorderResp.ok()).toBeTruthy();

  // Server truth: 'Doing' now precedes 'To Do' on this board.
  expect(order()).toContain('ORDER=Doing,To Do');

  // Drag it back so the fixture board stays canonical for the next run.
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes('/project/columns/reorder/') && r.request().method() === 'POST'
    ),
    (async () => {
      const backBox = await header('To Do').boundingBox();
      const frontLane = page.locator('[data-kanban-lane][data-kanban-lane-title="Doing"]');
      const frontBox = await frontLane.boundingBox();
      if (!backBox || !frontBox) throw new Error('lanes not measurable for restore');
      await pointerDrag(
        page,
        { x: backBox.x + backBox.width / 2, y: backBox.y + backBox.height / 2 },
        { x: frontBox.x + frontBox.width / 2, y: backBox.y + backBox.height / 2 }
      );
    })()
  ]);
  expect(order()).toContain('ORDER=To Do,Doing');
});
