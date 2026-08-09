import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * Settings ▸ Integrations smoke — flag-gated integration panels render when
 * their feature flag is ON for the operator's workspace.
 *
 * Regression (2026-08-09): `feature.vercel_posture` was on everywhere the
 * backend answered (default_enabled + global rule, and the flag rode
 * /identity/me/summary/), yet the Vercel panel never rendered — the frontend
 * gate read `isEnabled`, which resolved only the build-time env-features map
 * and could never see a backend-evaluated `feature.*` flag. This spec pins the
 * whole chain: backend evaluation → summary hydration → provider resolution →
 * the gated panel in the DOM.
 *
 * Throwaway operator in its own workspace (surfaces.smoke pattern) — the flag
 * must be ON for that workspace, which `default_enabled=True` provides; the
 * beforeAll asserts the backend evaluation so a flag flip fails loudly here
 * instead of as a mystery UI timeout.
 */
const EMAIL = 'integrations-e2e@qa.autosec.local';
const PASSWORD = 'IntegrationsPass123!';

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(HUD_ROOT_RE);
}

test.beforeAll(() => {
  const out = sh(
    [
      'from infrastructure.persistence.users.models import CustomUser, UserProfile',
      'from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership',
      'from components.shared_platform.infrastructure.services.feature_flags import is_feature_enabled',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'integrationse2e'})`,
      "u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      `u.set_password('${PASSWORD}'); u.save()`,
      "ws=Workspace.objects.all_objects().filter(workspace_owner=u).first() or Workspace.objects.create(workspace_name='Integrations E2E Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True)",
      "UserProfile.objects.update_or_create(user=u, defaults={'active_workspace_id': ws.id})",
      "WorkspaceMembership.objects.get_or_create(workspace=ws, user=u, defaults={'role':'owner','status':'active'})",
      "print('VERCEL_FLAG=' + str(is_feature_enabled('feature.vercel_posture', user=u, workspace_id=str(ws.id))))"
    ].join('; ')
  );
  // Fixture-stage guard: the panel test below is only meaningful when the
  // backend evaluates the flag ON for this workspace.
  if (!out.includes('VERCEL_FLAG=True')) {
    throw new Error(
      `feature.vercel_posture is OFF for the seeded workspace — seed output: ${out}`
    );
  }
});

test('Vercel panel renders in Settings ▸ Integrations when feature.vercel_posture is on', async ({
  page
}) => {
  await login(page);
  await page.goto('/?panel=settings&section=integrations');

  // The un-gated AWS connect card is the baseline — Integrations rendered.
  await expect(page.getByText('CONNECT AWS').first()).toBeVisible({
    timeout: 20_000
  });

  // The flag-gated Vercel card: heading + consent copy.
  await expect(page.getByText('VERCEL', { exact: true }).first()).toBeVisible({
    timeout: 20_000
  });
  await expect(
    page.getByText(/Posture-scan your Vercel estate/i).first()
  ).toBeVisible();

  // The link-a-team form opens (read-only — nothing is created).
  await page.getByRole('button', { name: 'Connect a team' }).click();
  await expect(
    page.getByPlaceholder('acme or team_a1b2c3').first()
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Link Vercel team' })
  ).toBeVisible();
});
