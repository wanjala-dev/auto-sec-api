/**
 * Central env contract for the tests/qa smoke harness.
 *
 * Mirrors the committed frontend `e2e/` suite's contract (E2E_* vars, same
 * defaults = the seeded demo login) so one shell environment drives both
 * suites. The legacy QA_* names are honoured as fallbacks so nothing that
 * scripted the old harness breaks.
 *
 *   E2E_BASE_URL  (QA_LOCAL_URL)       frontend origin   default http://localhost:3015
 *   E2E_EMAIL     (QA_ADMIN_EMAIL)     admin login       default test@autosec.local
 *   E2E_PASSWORD  (QA_ADMIN_PASSWORD)  admin password    default AutoSecTest2026!
 *
 * SAFETY: the demo admin login is used ONLY for read-only flows (login →
 * sign out). Every spec that registers users or mutates auth state (2FA
 * enrolment, password change, onboarding, membership writes) provisions its
 * own throwaway `*@qa.autosec.local` fixture via helpers/backend.ts — the two
 * seeded demo logins' auth state is never touched.
 */
export const E2E = {
  baseURL:
    process.env.E2E_BASE_URL ||
    process.env.QA_LOCAL_URL ||
    'http://localhost:3015',
  email:
    process.env.E2E_EMAIL ||
    process.env.QA_ADMIN_EMAIL ||
    'test@autosec.local',
  password:
    process.env.E2E_PASSWORD ||
    process.env.QA_ADMIN_PASSWORD ||
    'AutoSecTest2026!',
};

/** Matches the HUD root (origin + "/", optional query) on ANY base URL —
 *  replaces the old hardcoded /localhost:3001\/$/ assertions. */
export const HUD_ROOT_RE = /^https?:\/\/[^/]+\/(?:\?.*)?$/;

/**
 * Tenant-host smoke contract (tenant-hosts.smoke.spec.ts) — the local
 * multi-tenant parity stack: gateway path-split on *.auto-sec.ai + the shared
 * HUD dev server on :3050 (auto-sec-infra k8s/README.md "Local tenant-host
 * testing"). Hosts resolve inside Chromium via --host-resolver-rules (see the
 * `tenant-hosts` project in playwright.config.ts) — /etc/hosts is not needed.
 *
 * Defaults = the seeded local tenants. The wanjala/pooled credentials mirror
 * the seed defaults the same way E2E.email/password mirror the demo login;
 * override any of it via env for a differently-seeded environment.
 */
export const TENANT_QA = {
  /** Tenant hosts that must serve the branded HUD (CSV env override). */
  hosts: (
    process.env.QA_TENANT_HOSTS ||
    'faura.auto-sec.ai,acme.auto-sec.ai,senso.auto-sec.ai,wanjala.auto-sec.ai'
  )
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean),
  /** The tenant whose admin login the positive/isolation probes use. */
  loginHost: process.env.QA_TENANT_LOGIN_HOST || 'wanjala.auto-sec.ai',
  email: process.env.QA_TENANT_EMAIL || 'admin@wanjala.test',
  password: process.env.QA_TENANT_PASSWORD || 'WanjalaTest2026!',
  /** A DIFFERENT tenant host, where those credentials must NOT work. */
  crossHost: process.env.QA_TENANT_CROSS_HOST || 'faura.auto-sec.ai',
  /** The pooled demo admin — must work on autosec.local, not on a dedicated host. */
  pooledEmail: process.env.E2E_EMAIL || process.env.QA_ADMIN_EMAIL || 'test@autosec.local',
  pooledPassword:
    process.env.E2E_PASSWORD || process.env.QA_ADMIN_PASSWORD || 'AutoSecTest2026!',
};
