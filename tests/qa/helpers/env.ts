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
