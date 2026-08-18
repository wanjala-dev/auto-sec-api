import { test, expect, Page } from '@playwright/test';

import { TENANT_QA } from './helpers/env';

/**
 * Tenant-host smoke — the URL binds the tenant, end to end.
 *
 * Local multi-tenant parity (auto-sec-infra#28) means typing
 * http://<tenant>.auto-sec.ai serves the HUD through the gateway with
 * SAME-ORIGIN API calls, so the Host header is what picks the tenant's
 * database. This spec is the regression net for that whole chain:
 *
 *   gateway path-split (HUD at root, /api -> api svc, /ws -> channels)
 *   → same-origin API calls (no absolute base leaking to another host)
 *   → tenant-branded login screen (registry as the source of truth)
 *   → credential isolation (a login is only valid on its own host)
 *   → tenant-bound realtime (JWT websocket handshake on the tenant host)
 *   → the pooled console (autosec.local) untouched.
 *
 * HOSTS: resolved inside Chromium via --host-resolver-rules (see the
 * `tenant-hosts` project in playwright.config.ts) — /etc/hosts is NOT needed
 * for this spec. Prereqs: the local k8s stack up AND the shared tenant HUD
 * dev server running on :3050 (see auto-sec-infra k8s/README.md "Local
 * tenant-host testing"). The beforeAll probe fails loudly when either is down.
 *
 * SAFETY: read-only against seeded logins (single login attempts, no
 * mutations, no 2FA). The negative probes aim credentials at hosts whose
 * database does not contain that user at all, so no lockout counter on the
 * real account is ever advanced.
 */

const loginUrl = (host: string) => `http://${host}/identity/login`;

const brandOf = async (page: Page): Promise<{ name: string; branded: boolean }> =>
  page.evaluate(async () => {
    const res = await fetch('/api/v1/tenant/login-brand/');
    return res.json();
  });

const fillLogin = async (page: Page, email: string, password: string) => {
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Password' }).fill(password);
  await page.getByRole('button', { name: 'SIGN IN', exact: true }).click();
};

test.describe('tenant hosts — the URL binds the tenant', () => {
  test.beforeAll(async ({ request }) => {
    // Loud prereq probe: the gateway must be up AND the shared dev server
    // must be serving the tenant hosts. (request bypasses the browser's
    // resolver rules, so probe via 127.0.0.1 + Host header.)
    const probe = await request
      .get(`http://127.0.0.1/`, {
        headers: { Host: TENANT_QA.hosts[0] },
        timeout: 10_000,
      })
      .catch(() => null);
    if (!probe || !probe.ok()) {
      throw new Error(
        `tenant host ${TENANT_QA.hosts[0]} is not serving through the gateway. ` +
          'Prereqs: local k8s stack up (kubectl -n autosec get pods) AND the shared ' +
          'tenant dev server on :3050 (see auto-sec-infra k8s/README.md "Local tenant-host testing").'
      );
    }
  });

  for (const host of TENANT_QA.hosts) {
    test(`${host} serves the HUD login at root, branded from the registry`, async ({
      page,
    }) => {
      await page.goto(`http://${host}/`);
      // The SPA auth-guards root -> its login route, on the SAME host.
      await expect(page).toHaveURL(new RegExp(`^http://${host}/identity/login$`));
      await expect(page.getByRole('tab', { name: 'SIGN IN' })).toBeVisible();

      // The registry is the source of truth for the login identity — assert
      // the HEADING equals what the host's own login-brand endpoint says, so
      // the spec keeps passing when tenants are added or renamed.
      const brand = await brandOf(page);
      expect(brand.branded, `${host} must be a registered tenant host`).toBe(true);
      expect(brand.name.trim().length).toBeGreaterThan(0);
      await expect(page.getByText(brand.name.toUpperCase(), { exact: true })).toBeVisible();
      await expect(page.getByText('SECURED BY AUTO-SEC')).toBeVisible();
    });
  }

  test('API calls from a tenant page are same-origin (Host carries the tenant)', async ({
    page,
  }) => {
    const offOrigin: string[] = [];
    page.on('request', (req) => {
      const url = req.url();
      if (url.includes('/api/') && !url.startsWith(`http://${TENANT_QA.loginHost}/`)) {
        offOrigin.push(url);
      }
    });
    await page.goto(loginUrl(TENANT_QA.loginHost));
    await expect(page.getByRole('tab', { name: 'SIGN IN' })).toBeVisible();
    await fillLogin(page, TENANT_QA.email, TENANT_QA.password);
    await expect(page).toHaveURL(
      new RegExp(`^http://${TENANT_QA.loginHost}/(?:\\?.*)?$`)
    );
    expect(
      offOrigin,
      `every /api/ request must target the tenant origin; leaked: ${offOrigin.join(', ')}`
    ).toEqual([]);
  });

  test('a tenant login is only valid on its own host', async ({ page, browser }) => {
    // Positive: the tenant admin lands on the HUD on its own host.
    await page.goto(loginUrl(TENANT_QA.loginHost));
    await fillLogin(page, TENANT_QA.email, TENANT_QA.password);
    await expect(page).toHaveURL(new RegExp(`^http://${TENANT_QA.loginHost}/(?:\\?.*)?$`));

    // Negative: the same credentials on ANOTHER tenant host stay at the gate —
    // that host's database has no such user (fresh context: no shared storage).
    const other = await browser.newContext();
    const otherPage = await other.newPage();
    await otherPage.goto(loginUrl(TENANT_QA.crossHost));
    await fillLogin(otherPage, TENANT_QA.email, TENANT_QA.password);
    await expect(otherPage).toHaveURL(new RegExp(`^http://${TENANT_QA.crossHost}/identity/login$`));

    // Negative: the pooled demo admin does not exist in a dedicated tenant.
    const pooled = await browser.newContext();
    const pooledPage = await pooled.newPage();
    await pooledPage.goto(loginUrl(TENANT_QA.loginHost));
    await fillLogin(pooledPage, TENANT_QA.pooledEmail, TENANT_QA.pooledPassword);
    await expect(pooledPage).toHaveURL(
      new RegExp(`^http://${TENANT_QA.loginHost}/identity/login$`)
    );

    await other.close();
    await pooled.close();
  });

  test('realtime websocket handshakes on the tenant host (/ws → channels)', async ({
    page,
  }) => {
    await page.goto(loginUrl(TENANT_QA.loginHost));
    await fillLogin(page, TENANT_QA.email, TENANT_QA.password);
    // Anchored HUD-root URL: "^http://host/" alone also matches the login
    // route, which let the probe run before the token was stored.
    await expect(page).toHaveURL(
      new RegExp(`^http://${TENANT_QA.loginHost}/(?:\\?.*)?$`)
    );
    // The token write races the redirect by a tick — wait for it briefly.
    await page.waitForFunction(() => !!localStorage.getItem('token'), null, {
      timeout: 5_000,
    });

    // Open a websocket FROM the page with the session's JWT: the handshake
    // only succeeds if the gateway routed /ws to channels AND channels
    // validated the token against THIS tenant's database. A misroute to the
    // dev server (or a cross-tenant token) never reaches 'open'.
    const outcome = await page.evaluate(
      () =>
        new Promise<string>((resolve) => {
          const token = localStorage.getItem('token') || '';
          if (!token) {
            resolve('no-token');
            return;
          }
          const ws = new WebSocket(
            `ws://${location.host}/ws/notifications/?token=${encodeURIComponent(token)}`
          );
          const timer = setTimeout(() => {
            ws.close();
            resolve('timeout');
          }, 15_000);
          ws.onopen = () => {
            clearTimeout(timer);
            ws.close();
            resolve('open');
          };
          ws.onerror = () => {
            clearTimeout(timer);
            resolve('error');
          };
        })
    );
    expect(outcome).toBe('open');
  });

  test('the pooled console (autosec.local) is untouched', async ({ request }) => {
    const health = await request.get('http://autosec.local/api/health/');
    expect(health.ok()).toBe(true);
    expect(await health.json()).toEqual({ status: 'ok' });

    // The demo admin still authenticates on the pooled host (single, read-only
    // login POST — the demo account's auth state is never mutated).
    const login = await request.post('http://autosec.local/api/v1/identity/login/', {
      data: { email: TENANT_QA.pooledEmail, password: TENANT_QA.pooledPassword },
    });
    expect(login.status()).toBe(200);
  });
});
