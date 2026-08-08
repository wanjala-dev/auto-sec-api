import { test, expect, Page } from '@playwright/test';

import { sh } from './helpers/backend';
import { HUD_ROOT_RE } from './helpers/env';

/**
 * Collaboration smoke — Direct Messages + the operator social feed:
 * DM thread renders + send persists; feed post/like/comment persist.
 * Provisions its own throwaway operator + workspace + a DM counterpart.
 *
 * Both surfaces are HUD overlay panels reached via the ?panel= deep link
 * (messaging / social) — the old header entry buttons ("Direct messages" /
 * "Operator feed") no longer exist. The social feed is server-gated behind
 * feature.social_feed, so the fixture seeds a workspace-scoped flag rule for
 * its own throwaway workspace (never a global rule).
 */
const EMAIL = 'collab-e2e@qa.autosec.local';
const PASSWORD = 'CollabPass123!';
const PEER = 'collab-peer@qa.autosec.local';

async function login(page: Page) {
  await page.goto('/identity/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(EMAIL);
  await page.getByRole('textbox', { name: 'Password' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
  await expect(page).toHaveURL(HUD_ROOT_RE);
}

test.beforeAll(() => {
  sh(
    [
      'from infrastructure.persistence.users.models import CustomUser, UserProfile',
      'from infrastructure.persistence.workspaces.models import Workspace',
      'from infrastructure.persistence.messaging.models import Conversation, ConversationParticipant, Message',
      `u,_=CustomUser.objects.get_or_create(email='${EMAIL}', defaults={'username':'collabe2e'})`,
      "u.is_verified=True; u.is_active=True; u.is_onboard_complete=True",
      `u.set_password('${PASSWORD}'); u.save()`,
      "ws=Workspace.objects.all_objects().filter(workspace_owner=u).first() or Workspace.objects.create(workspace_name='Collab E2E Org', workspace_type='teamspace', workspace_owner=u, status='active', is_active=True)",
      "UserProfile.objects.update_or_create(user=u, defaults={'active_workspace_id': ws.id})",
      `p,_=CustomUser.objects.get_or_create(email='${PEER}', defaults={'username':'collabpeer','first_name':'Nova','last_name':'Reyes'})`,
      "c=Conversation.objects.filter(participants__user=u).filter(participants__user=p).first()",
      "c=c or Conversation.objects.create(conversation_type='private')",
      "ConversationParticipant.objects.get_or_create(conversation=c, user=u, defaults={'role':'owner'})",
      "ConversationParticipant.objects.get_or_create(conversation=c, user=p, defaults={'role':'member'})",
      "Message.objects.get_or_create(conversation=c, sender=p, body='E2E seed message', defaults={'message_type':'text'})",
      // The social feed is gated behind feature.social_feed — enable it for
      // THIS throwaway workspace only (workspace-scoped rule, no global bleed).
      'from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule',
      'from components.shared_platform.infrastructure.services.feature_flags import bump_feature_flags_version',
      "f,_=FeatureFlag.objects.get_or_create(key='feature.social_feed', defaults={'default_enabled': False})",
      "FeatureFlagRule.objects.get_or_create(flag=f, scope='workspace', workspace=ws, defaults={'enabled': True})",
      'bump_feature_flags_version()',
      "print('ready')"
    ].join('; ')
  );
});

test('DM: thread renders + send persists', async ({ page }) => {
  // MessageSendThrottle is 60/min PER USER (anti-spam, correct product
  // behaviour). Repeated harness runs exhaust the fixture user's bucket and the
  // send 429s — so clear just this user's throttle key first. Test-environment
  // setup through the same api-pod glue as the fixtures; the throttle itself is
  // never weakened.
  sh(
    [
      'from django.core.cache import cache',
      'from infrastructure.persistence.users.models import CustomUser',
      `u=CustomUser.objects.get(email='${EMAIL}')`,
      "cache.delete('throttle_user_%s' % u.pk)",
      "print('throttle-cleared')"
    ].join('; ')
  );

  await login(page);
  // Messaging is a HUD overlay panel — deep-link it open.
  await page.goto('/?panel=messaging');
  const row = page.locator('button.border-l-2', { hasText: 'Nova' }).first();
  await expect(row).toBeVisible();
  await row.dispatchEvent('click');

  const body = `Ping ${Date.now().toString().slice(-5)}`;
  await page.locator('input[placeholder="Message…"]').fill(body);
  // Send via the button, not Enter: it stays disabled until the controlled
  // input's state committed, so clicking it can never race the React render.
  const send = page.getByRole('button', { name: 'Send' });
  await expect(send).toBeEnabled();
  // Await the send POST and assert it succeeded — a silent backend failure
  // (throttle, 4xx) otherwise surfaces as an unexplained "message not visible".
  const [sendResp] = await Promise.all([
    page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/messages/send/')
    ),
    send.click()
  ]);
  expect(sendResp.ok()).toBeTruthy();

  // Scoped .first(): the body renders in BOTH the thread bubble and the
  // conversation-list last-message preview (strict mode).
  await expect(page.getByText(body).first()).toBeVisible();

  const out = sh(
    [
      'from infrastructure.persistence.messaging.models import Message',
      `print('MSG=' + str(Message.objects.filter(body='${body}').exists()))`
    ].join('; ')
  );
  expect(out).toContain('MSG=True');
});

test('Feed: post + like + comment persist', async ({ page }) => {
  await login(page);
  // The operator feed is a HUD overlay panel — deep-link it open.
  await page.goto('/?panel=social');

  const body = `E2E status ${Date.now().toString().slice(-5)}`;
  await page
    .locator('textarea[placeholder="Share an update, IOC, or hand-off…"]')
    .fill(body);
  // exact: the nav's POSTURE / CLOUD POSTURE buttons also match "Post".
  await page.getByRole('button', { name: 'Post', exact: true }).dispatchEvent('click');
  await expect(page.getByText(body)).toBeVisible();

  // Like + comment on the new post's card (stable aria-labels).
  await page.getByLabel('Like post').first().dispatchEvent('click');
  await page.getByLabel('Toggle comments').first().dispatchEvent('click');
  await page.locator('input[placeholder="Reply…"]').first().fill('ack-e2e');
  await page
    .locator('input[placeholder="Reply…"]')
    .first()
    .press('Enter');

  const out = sh(
    [
      'from infrastructure.persistence.social.models import Post, Comment',
      `p=Post.objects.filter(body='${body}').first()`,
      "print('LIKES=' + str(p.likes.count() if p else -1))",
      "print('COMMENTS=' + str(Comment.objects.filter(comment='ack-e2e').exists()))"
    ].join('; ')
  );
  expect(out).toMatch(/LIKES=[1-9]/);
  expect(out).toContain('COMMENTS=True');
});
