import { test, expect, Page } from '@playwright/test';
import { execSync } from 'node:child_process';

/**
 * Collaboration smoke — Direct Messages + the operator social feed:
 * DM thread renders + send persists; feed post/like/comment persist.
 * Provisions its own operator + workspace + a DM counterpart. Idempotent.
 */
const EMAIL = 'collab-e2e@octopus.local';
const PASSWORD = 'CollabPass123!';
const PEER = 'collab-peer@octopus.local';
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
      "print('ready')"
    ].join('; ')
  );
});

test('DM: thread renders + send persists', async ({ page }) => {
  await login(page);
  await page.locator('button[title="Direct messages"]').click();
  const row = page.locator('button.border-l-2', { hasText: 'Nova' }).first();
  await expect(row).toBeVisible();
  await row.dispatchEvent('click');

  const body = `Ping ${Date.now().toString().slice(-5)}`;
  await page.locator('input[placeholder="Message…"]').fill(body);
  await page.locator('input[placeholder="Message…"]').press('Enter');
  await expect(page.getByText(body)).toBeVisible();

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
  await page.locator('button[title="Operator feed"]').click();

  const body = `E2E status ${Date.now().toString().slice(-5)}`;
  await page
    .locator('textarea[placeholder="Share an update, IOC, or hand-off…"]')
    .fill(body);
  await page.getByRole('button', { name: 'Post' }).dispatchEvent('click');
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
