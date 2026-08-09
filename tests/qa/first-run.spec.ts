import { execSync } from 'node:child_process';

import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { E2E, HUD_ROOT_RE } from './helpers/env';

/**
 * FIRST-RUN CUSTOMER JOURNEY — the from-zero walk a brand-new customer takes:
 *
 *   register → verify email → create a workspace → default desk sanity →
 *   invite a teammate (accept via the invitation token) → viewer deny →
 *   connect GitHub (real PAT) → repo scan → finding + triage chip + snippet →
 *   connect Slack (real webhook) → AWS wizard to the role handoff +
 *   fail-loud verify → teardown.
 *
 * Every spec is honest about its preconditions:
 *   - The email-verification step uses a REAL minted token (kubectl → api pod)
 *     because no inbox is readable from the harness. Delivery itself is now
 *     proven separately: the resend leg asserts the Celery send task COMPLETES
 *     (SES-accepted when SMTP creds are wired; console print otherwise), and
 *     all throwaway identities use SES mailbox-simulator addresses so real
 *     sends never bounce.
 *   - The invite leg drives the REAL public /invite/accept page — the same
 *     URL the invite email carries — not the raw accept endpoint.
 *   - GitHub steps need E2E_GITHUB_PAT + E2E_GITHUB_REPO and skip LOUDLY
 *     without them. The repo scan also needs feature.code_security, which is
 *     default-OFF for every workspace — the spec seeds the per-workspace flag
 *     rule the way an operator would today (that gap is reported).
 *   - Slack verify needs E2E_SLACK_WEBHOOK (it posts a REAL message) and
 *     skips loudly without it; the malformed-URL fail-loud check runs always.
 *   - A real AWS cross-account connect cannot be automated from here (it
 *     requires deploying an IAM role in a live AWS account). The spec walks
 *     the wizard to the CloudFormation handoff and asserts a bogus account
 *     fails VERIFY with a visible error — not a spinner, not silence.
 *
 * Idempotent: fixed throwaway identities under *@qa.autosec.local, cleaned in
 * beforeAll (crash-safe re-runs) and afterAll. Never touches the demo
 * workspace or the demo logins.
 */
// SES mailbox-simulator addresses (success+label@simulator.amazonses.com):
// with real SMTP creds wired into the cluster these registrations/invites now
// SEND — the simulator accepts every message with zero bounce/reputation
// impact, while a console-backend environment just prints them. Never point
// these at a fake domain again (each run would bounce off SES).
const OWNER = 'success+first-run-owner@simulator.amazonses.com';
const OWNER_PASSWORD = 'FirstRunOwner123!';
const MEMBER = 'success+first-run-viewer@simulator.amazonses.com';
const MEMBER_PASSWORD = 'FirstRunViewer123!';
const WS_NAME = 'First Run Org';

const GITHUB_PAT = process.env.E2E_GITHUB_PAT || '';
const GITHUB_REPO = process.env.E2E_GITHUB_REPO || '';
const SLACK_WEBHOOK = process.env.E2E_SLACK_WEBHOOK || '';

/** Remove every trace of the throwaway journey (users, workspaces, invites).
 *  Workspace delete cascades the integration connections + flag rules. */
const wipeJourneyRows = () =>
  sh(
    [
      'from infrastructure.persistence.users.models import AuthAuditEvent, CustomUser',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from infrastructure.persistence.team.models import Invitation',
      'from infrastructure.persistence.notifications.models import Notification',
      `Invitation.objects.filter(email__in=['${OWNER}','${MEMBER}']).delete()`,
      // Audit rows keep the email after user delete (user is SET_NULL) — wipe
      // them so the resend-audit assertion is exact on every (re)run.
      `AuthAuditEvent.objects.filter(email__in=['${OWNER}','${MEMBER}']).delete()`,
      // Reset the resend throttle counters (3/hour per email, 10/hour per IP
      // in redis) so repeated suite runs inside an hour never 429 the banner.
      'from django.core.cache import cache',
      "getattr(cache, 'delete_pattern', lambda *_: None)('*auth_resend_verification*')",
      // Includes the synthetic AI-teammate user the workspace bootstrap
      // provisions for 'First Run Org' — workspace delete orphans it.
      `users=CustomUser.objects.filter(email__in=['${OWNER}','${MEMBER}','first-run-org@ai-teammate.local'])`,
      'Workspace.objects.all_objects().filter(workspace_owner__in=users).delete()',
      // The teammate's AITeammateProfile PROTECTs its user row and can
      // outlive the workspace delete — drop it before the user delete.
      'from infrastructure.persistence.ai.models import AITeammateProfile',
      'AITeammateProfile.objects.filter(user__in=users).delete()',
      'Notification.objects.filter(recipient__in=users).delete()',
      'Notification.objects.filter(actor__in=users).delete()',
      'users.delete()',
      "print('clean-ok')"
    ].join('; ')
  );

const cleanJourneyFixtures = () => {
  // Notifications are created ASYNC (celery) on workspace/membership events,
  // so a fresh row can land between the notification sweep and the user
  // delete and trip the recipient FK at commit. One settle-and-retry pass
  // absorbs the race without hiding a real failure.
  try {
    wipeJourneyRows();
  } catch {
    execSync('sleep 3');
    wipeJourneyRows();
  }
};

const login = async (page: Page, email: string, password: string) => {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
};

const loginToHud = async (page: Page, email: string, password: string) => {
  await login(page, email, password);
  await expect(page).toHaveURL(HUD_ROOT_RE);
  await expect(page.getByText('AUTO-SEC').first()).toBeVisible();
};

/** ?panel= deep links are read once on mount — always full goto. */
const openIntegrations = async (page: Page) => {
  await page.goto('/?panel=settings&section=integrations');
  await expect(page.getByText('CODE REPOSITORIES')).toBeVisible({
    timeout: 20_000
  });
};

test.describe.serial('first-run customer journey', () => {
  test.beforeAll(() => {
    cleanJourneyFixtures();
  });

  test.afterAll(() => {
    cleanJourneyFixtures();
  });

  test('step 1 — register a fresh account; the verification gate blocks login until the (minted) email token verifies', async ({
    page
  }) => {
    // Register through the real UI form.
    await page.goto('/identity/login');
    await page.getByRole('tab', { name: 'REGISTER' }).click();
    await page.getByRole('textbox', { name: 'Full name' }).fill('First Run');
    await page.getByRole('textbox', { name: 'Email' }).fill(OWNER);
    await page.getByRole('textbox', { name: 'Password' }).fill(OWNER_PASSWORD);
    const create = page.getByRole('button', { name: 'CREATE ACCOUNT' });
    await page.getByRole('button', { name: /I agree to the Terms/i }).click();
    await expect(create).toBeEnabled();
    await create.click();
    await expect(page.getByText(/Account created\./i).first()).toBeVisible();

    // The verification gate: login BEFORE verifying must be refused, visibly.
    await login(page, OWNER, OWNER_PASSWORD);
    await expect(page).toHaveURL(/\/identity\/login$/);
    await expect(page.getByText(/not verified/i).first()).toBeVisible();

    // RECOVERY (Blocker A): the refusal is no longer a dead end — a banner
    // offers a resend, the endpoint answers with the neutral 202 UX, the
    // resend is audit-logged, and the Celery send task actually completes.
    const banner = page.getByTestId('not-verified-banner');
    await expect(banner).toBeVisible();
    await banner
      .getByRole('button', { name: /RESEND VERIFICATION EMAIL/i })
      .click();
    await expect(
      page.getByText(/a fresh verification email is on its way/i)
    ).toBeVisible();

    const auditOut = sh(
      [
        'from infrastructure.persistence.users.models import AuthAuditEvent',
        `n=AuthAuditEvent.objects.filter(event_code='auth.email_verification_resent', email='${OWNER}').count()`,
        "print('RESEND_AUDIT=%d' % n)"
      ].join('; ')
    );
    // >=1: a Playwright retry of this spec legitimately resends again.
    expect(auditOut).toMatch(/RESEND_AUDIT=[1-9]/);

    // The queued task ran to completion in the worker (grep the marker the
    // task logs — honest delivery, not an API that claims success silently).
    let taskDone = false;
    for (let i = 0; i < 15 && !taskDone; i++) {
      const logs = execSync(
        'kubectl -n autosec logs deploy/celery-worker --since=10m'
      ).toString();
      taskDone = logs.includes('identity.send_verification_email completed');
      if (!taskDone) execSync('sleep 2');
    }
    expect(taskDone, 'identity.send_verification_email completed in the worker').toBeTruthy();

    // Mint the exact token the verification email would carry (this
    // deployment's email backend is console — see the report), then drive the
    // real confirm page.
    const out = sh(
      [
        'from infrastructure.persistence.users.models import CustomUser',
        'from rest_framework_simplejwt.tokens import RefreshToken',
        `u=CustomUser.objects.get(email='${OWNER}')`,
        "print('TOKEN=%s' % RefreshToken.for_user(u).access_token)"
      ].join('; ')
    );
    const token = out.match(/TOKEN=(\S+)/)?.[1];
    expect(token, 'verification token minted in the api pod').toBeTruthy();
    await page.goto(`/identity/email-confirmed?token=${token}`);
    await expect(page.getByText(/EMAIL VERIFIED/i)).toBeVisible();
  });

  test('step 2 — create the workspace from zero; the default desk renders BRIEF + setup affordances, not blanks', async ({
    page
  }) => {
    await login(page, OWNER, OWNER_PASSWORD);
    await expect(page).toHaveURL(HUD_ROOT_RE);

    // Guided create flow (blocking overlay over the HUD).
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeVisible();
    await page.getByPlaceholder(/Workspace name/i).fill(WS_NAME);
    await page.getByRole('button', { name: 'CREATE WORKSPACE' }).click();
    await page.getByRole('button', { name: 'CONTINUE', exact: true }).click();
    await page
      .getByRole('button', { name: 'ENTER COMMAND CENTER' })
      .click();
    await expect(page).toHaveURL(HUD_ROOT_RE);
    await expect(page.getByText('ESTABLISH WORKSPACE')).toBeHidden();

    // Default desk: BRIEF card + CODE REPOS empty state with its connect
    // affordance — a fresh workspace must never present dead blanks.
    await expect(page.getByText('BRIEF', { exact: true }).first()).toBeVisible(
      { timeout: 20_000 }
    );
    await expect(
      page.getByText(/No repositories linked/i).first()
    ).toBeVisible();

    // The setup funnel: 0/5 on a fresh workspace, and the chip opens the
    // actionable GETTING STARTED checklist.
    const setupChip = page.getByRole('button', { name: /SETUP 0\/5/ });
    await expect(setupChip).toBeVisible();
    await setupChip.click();
    await expect(page.getByText('GETTING STARTED')).toBeVisible();
    for (const label of [
      'Connect a cloud account',
      'Run your first scan',
      'Triage a finding',
      'Invite a teammate',
      'Connect Slack'
    ]) {
      // exact — each row also renders a detail line that repeats the label.
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('step 3 — invite a viewer; the invitation token enrolls them with the viewer role', async ({
    page
  }) => {
    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await page.goto('/?panel=settings&section=members');
    await page.getByRole('tab', { name: /INVITES/ }).click();
    await page.getByPlaceholder('operator@org.com').fill(MEMBER);
    await page
      .getByRole('combobox', { name: 'Role' })
      .selectOption('viewer');
    await page.getByRole('button', { name: /Invite/ }).dispatchEvent('click');
    await expect(page.getByText(/Invite sent/)).toBeVisible();

    // Read the invitation's magic-link token from the live DB — the exact
    // token the emailed accept link carries (an inbox can't be read from
    // here; the URL below is byte-identical to the email's link).
    const out = sh(
      [
        'from infrastructure.persistence.team.models import Invitation',
        `inv=Invitation.objects.filter(email='${MEMBER}', status='invited').first()`,
        "print('ITOKEN=%s' % (inv.token if inv else 'MISSING'))"
      ].join('; ')
    );
    const token = out.match(/ITOKEN=(\S+)/)?.[1];
    expect(token, 'invitation token present in DB').toBeTruthy();
    expect(token).not.toBe('MISSING');

    // Drop the owner's session — the teammate opens this link logged out.
    await page.evaluate(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });

    // A mangled token must be an HONEST dead end, leaking nothing usable.
    await page.goto('/invite/accept?token=bogus-token');
    await expect(page.getByText('INVITE UNAVAILABLE')).toBeVisible();

    // Blocker B: the REAL public accept page — invite facts render, the
    // new user sets a password, and the returned JWTs land them on the HUD.
    await page.goto(`/invite/accept?token=${token}`);
    await expect(page.getByText('JOIN WORKSPACE')).toBeVisible();
    // exact — the AuthShell subtitle also carries the workspace name.
    await expect(page.getByText(WS_NAME, { exact: true })).toBeVisible();
    await expect(page.getByText(MEMBER)).toBeVisible();
    await page.getByPlaceholder('Full name (optional)').fill('Vera Viewer');
    await page.getByPlaceholder('Password', { exact: true }).fill(MEMBER_PASSWORD);
    await page.getByPlaceholder('Confirm password').fill(MEMBER_PASSWORD);
    await page
      .getByRole('button', { name: 'SET PASSWORD & JOIN' })
      .click();
    await expect(page).toHaveURL(HUD_ROOT_RE, { timeout: 20_000 });
    await expect(page.getByText('AUTO-SEC').first()).toBeVisible();

    // The membership row landed with the invited role.
    const roleOut = sh(
      [
        'from infrastructure.persistence.users.models import CustomUser',
        'from infrastructure.persistence.workspaces.models import WorkspaceMembership',
        `m=WorkspaceMembership.objects.filter(user__email='${MEMBER}').first()`,
        "print('ROLE=%s STATUS=%s' % ((m.role, m.status) if m else ('NONE','NONE')))"
      ].join('; ')
    );
    expect(roleOut).toContain('ROLE=viewer');
    expect(roleOut).toContain('STATUS=active');

    // The invited viewer can sign in with the password they set on accept.
    // Drop the owner's stored session first — /identity/login bounces back
    // to the HUD whenever a token is still in storage.
    await page.evaluate(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
    await loginToHud(page, MEMBER, MEMBER_PASSWORD);
  });

  test('step 3b — the viewer is denied integration mutations (visible deny, nothing written)', async ({
    page
  }) => {
    await loginToHud(page, MEMBER, MEMBER_PASSWORD);
    await openIntegrations(page);

    // Attempt a Slack channel connect as the viewer: the server must refuse
    // and the UI must SAY so.
    await page.getByRole('button', { name: 'Add channel' }).click();
    const form = page.getByTestId('delivery-add-form');
    await expect(form).toBeVisible();
    // exact — the CHANNEL input's '#sec-alerts' placeholder also substring-matches.
    await form.getByPlaceholder('Sec-alerts', { exact: true }).fill('Viewer Denied');
    // Well-formed dummy, assembled at runtime so secret scanning never sees
    // a webhook-shaped literal in the source (repo rule: no bypasses).
    const dummyWebhook = ['https://hooks.slack.com', 'services', 'T0000', 'B0000', 'x'.repeat(24)].join('/');
    await form
      .getByPlaceholder('https://hooks.slack.com/services/…')
      .fill(dummyWebhook);
    await form.getByRole('button', { name: 'Connect Slack' }).click();
    await expect(page.getByText(/Admin only/i).first()).toBeVisible();

    // Nothing landed in the DB.
    const out = sh(
      [
        'from infrastructure.persistence.integrations.models import DeliveryConnection',
        `print('CHANNELS=%d' % DeliveryConnection.objects.filter(workspace__workspace_name='${WS_NAME}').count())`
      ].join('; ')
    );
    expect(out).toContain('CHANNELS=0');
  });

  test('step 3c — the setup checklist ticks the invite step (1/5) after reload', async ({
    page
  }) => {
    // The chip only refetches on mount — a reload must show the new count.
    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await expect(
      page.getByRole('button', { name: /SETUP 1\/5/ })
    ).toBeVisible({ timeout: 20_000 });
  });

  test('step 4 — connect GitHub (VCS) with a real PAT and verify repo access', async ({
    page
  }) => {
    test.skip(
      !GITHUB_PAT || !GITHUB_REPO,
      'E2E_GITHUB_PAT / E2E_GITHUB_REPO not set — cannot walk the real GitHub connect. ' +
        'Export a fine-grained PAT (contents + PR write) and an owner/repo to run the most important leg of this journey.'
    );

    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await openIntegrations(page);

    await page.getByRole('button', { name: 'Link repo' }).click();
    await page
      .getByPlaceholder(/acme\/app/)
      .fill(GITHUB_REPO);
    await page.getByPlaceholder('github_pat_…').fill(GITHUB_PAT);
    await page.getByRole('button', { name: 'Link GitHub repos' }).click();
    await expect(
      page.getByText(/Repository connected — verify it/i)
    ).toBeVisible();

    // Verify: token + repo access probed for real; failure surfaces the
    // last_error in a toast — success is explicit.
    await page.getByRole('button', { name: 'VERIFY', exact: true }).first().click();
    await expect(
      page.getByText(/Reachable — token \+ repo access confirmed/i)
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('CONNECTED').first()).toBeVisible();
  });

  test('step 4b — repo scan lands findings with the triage chip + code snippet; draft-PR affordance is owner-gated', async ({
    page
  }) => {
    test.skip(
      !GITHUB_PAT || !GITHUB_REPO,
      'E2E_GITHUB_PAT / E2E_GITHUB_REPO not set — skipping the scan→findings→draft-PR leg.'
    );
    test.setTimeout(600_000); // a real SAST scan job takes minutes

    // feature.code_security is default-OFF for every workspace (per-workspace
    // opt-in) — seed the flag rule exactly the way an operator must today.
    sh(
      [
        'from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule',
        'from infrastructure.persistence.workspaces.models import Workspace',
        'from components.shared_platform.infrastructure.services.feature_flags import bump_feature_flags_version',
        `ws=Workspace.objects.all_objects().get(workspace_name='${WS_NAME}')`,
        "f,_=FeatureFlag.objects.get_or_create(key='feature.code_security', defaults={'default_enabled': False})",
        "FeatureFlagRule.objects.get_or_create(flag=f, scope='workspace', workspace=ws, defaults={'enabled': True})",
        'bump_feature_flags_version()',
        "print('flag-ok')"
      ].join('; ')
    );

    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await openIntegrations(page);

    // Owner-only: allow the triage agent to open draft PRs, so the FIX READY
    // path can surface its affordance.
    const capability = page.getByRole('button', { name: 'Turn on' });
    if (await capability.isVisible().catch(() => false)) {
      await capability.click();
    }

    // Fire the scan from the per-repo row.
    await page
      .getByRole('button', { name: 'SCAN', exact: true })
      .first()
      .click();
    await expect(
      page.getByText(/Code scan started for/i)
    ).toBeVisible({ timeout: 20_000 });

    // Wait for the scan to complete: the repo row's recency stamp flips from
    // RUNNING back to a fresh "just now" state (the status poller runs every
    // 30s). Then the scan-history callout must show the latest run.
    const stamp = page.locator(`[data-scan-ago="${GITHUB_REPO}"]`);
    await expect
      .poll(
        async () => {
          const scanBtn = page
            .getByRole('button', { name: /RUNNING…|STARTING…|SCAN|~\d+m/ })
            .first();
          return (await scanBtn.textContent())?.trim() || '';
        },
        { timeout: 540_000, intervals: [15_000] }
      )
      .not.toMatch(/RUNNING|STARTING/);

    await stamp.click();
    await expect(page.getByText(/SCAN HISTORY/)).toBeVisible();
    await expect(page.locator('[data-scan-result]').first()).toBeVisible();
    await page
      .getByRole('button', { name: /VIEW CURRENT FINDINGS FOR THIS REPO/i })
      .click();

    // Findings panel: a finding row exists; open it and assert the triage
    // state chip + the sanitized code snippet.
    await expect(
      page.getByText('No findings match these filters.')
    ).toBeHidden();
    await page
      .locator('button[title="Open finding detail"]')
      .first()
      .click();
    await expect(page.getByTestId('triage-state-chip')).toBeVisible();
    const sast = page.getByTestId('sast-finding-detail');
    await expect(sast).toBeVisible();
    await expect(sast.getByText('Matched code')).toBeVisible();

    // The draft-PR affordance: either the fix is already proposed (FIX READY
    // → VIEW DRAFT PR / preview affordance) or the owner sees the DRAFT FIX
    // PR trigger. Whichever state triage is in, an owner-facing affordance
    // must exist — its absence is the bug this walk exists to catch.
    const affordance = page
      .getByTestId('draft-fix-pr')
      .or(page.getByText(/VIEW DRAFT PR|PREVIEW & OPEN DRAFT PR|QUEUED FOR TRIAGE|DRAFTING FIX/i).first());
    await expect(affordance).toBeVisible({ timeout: 180_000 });
  });

  test('step 5 — Slack: a malformed webhook is refused loudly; a real webhook connects + verifies', async ({
    page
  }) => {
    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await openIntegrations(page);

    // Fail-loud validation (no secret needed): a non-Slack URL must be
    // refused with the exact reason, and nothing stored.
    await page.getByRole('button', { name: 'Add channel' }).click();
    const form = page.getByTestId('delivery-add-form');
    await form.getByPlaceholder('Sec-alerts', { exact: true }).fill('First Run Alerts');
    await form
      .getByPlaceholder('https://hooks.slack.com/services/…')
      .fill('https://example.com/not-a-slack-webhook');
    await form.getByRole('button', { name: 'Connect Slack' }).click();
    await expect(
      page.getByText(/Slack webhook URLs must look like/i)
    ).toBeVisible();

    if (!SLACK_WEBHOOK) {
      test.info().annotations.push({
        type: 'skip-partial',
        description:
          'E2E_SLACK_WEBHOOK not set — the real connect+verify leg (posts a live test message) was skipped. Only the fail-loud validation ran.'
      });
      return;
    }

    // Real connect + verify (posts a REAL message to the channel).
    await form
      .getByPlaceholder('https://hooks.slack.com/services/…')
      .fill(SLACK_WEBHOOK);
    await form.getByRole('button', { name: 'Connect Slack' }).click();
    await expect(
      page.getByText(/Channel connected — verify it/i)
    ).toBeVisible();
    const row = page.getByTestId('delivery-row').first();
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: 'VERIFY', exact: true }).click();
    await expect(
      page.getByText(/Test message delivered — check the channel/i)
    ).toBeVisible({ timeout: 30_000 });
    await expect(row.getByText('CONNECTED')).toBeVisible();
  });

  test('step 6 — AWS wizard: role handoff artifacts are produced; a bogus account fails VERIFY visibly', async ({
    page
  }) => {
    // A REAL cross-account connect needs an IAM role deployed in a live AWS
    // account — that handshake cannot be automated from this harness and is
    // deliberately not faked. This walks everything up to the handoff and
    // asserts the failure surface is honest.
    await loginToHud(page, OWNER, OWNER_PASSWORD);
    await openIntegrations(page);

    await page.getByRole('button', { name: 'Connect an account' }).click();
    await page
      .getByPlaceholder('AWS account id (12 digits)')
      .fill('111111111111');
    await page.getByRole('button', { name: 'Create connection' }).click();

    // Deploy-role stage: the external id + a real CloudFormation template
    // must be produced (quick-create link renders only when a hosted
    // template URL is configured — the copyable template is the invariant).
    // Case-sensitive regex: the connection row behind the wizard renders a
    // lowercase 'external id: …' that a plain string match also hits.
    await expect(page.getByText(/External ID:/)).toBeVisible({
      timeout: 20_000
    });
    await expect(page.getByText('Generating template…')).toBeHidden({
      timeout: 20_000
    });
    await expect(
      page.getByRole('button', { name: /Copy template|Copy Terraform/ })
    ).toBeVisible();
    await page.getByRole('button', { name: 'I deployed the role' }).click();

    // Test stage: verifying a role that does not exist must fail LOUDLY —
    // a visible error, the button released (no eternal spinner), and no
    // green "Verified" state.
    await page.getByRole('button', { name: 'Test connection' }).click();
    await expect(
      page.getByText(/Verification failed|is the role deployed|error/i).first()
    ).toBeVisible({ timeout: 60_000 });
    await expect(
      page.getByRole('button', { name: 'Test connection' })
    ).toBeVisible();
    await expect(page.getByText(/✓ Verified/)).toBeHidden();

    // The connection row records the honest ERROR state.
    await openIntegrations(page);
    const row = page.getByText('111111111111').first();
    await expect(row).toBeVisible();
    await expect(page.getByText('ERROR', { exact: true }).first()).toBeVisible();
  });
});
