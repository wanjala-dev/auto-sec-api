# ADR 0016 — Provider-agnostic delivery channels behind the notifications funnel (Slack first)

Status: Proposed (2026-08-04) — design only; the build follows this spec.

Relates to: **ADR 0008** (`LogSourcePort` — the driven-adapter-behind-a-port + per-workspace-config
model + registry template, pointing *inbound*), **ADR 0010** (`VcsPort` — the same template pointing
*outbound*, and the "un-productized connection with no CRUD/no panel" failure mode this ADR fixes a
second instance of), **ADR 0004** (C-rules — C1 event decoupling via the shared kernel), **ADR 0015**
(risk-acceptance expiry — one of the default events this channel carries), the notifications
delivery-channel funnel (`DeliveryChannel` / `NotificationDelivery` / per-channel sender tasks), and
the standing idea note (Henry): *a provider-agnostic delivery/notification-channel port + adapter —
same seam as log sources / VCS, pointing OUTBOUND; add Slack in Settings ▸ Integrations; REUSE the
existing notifications dispatch funnel — Slack = a new delivery channel, not a parallel notifier.*

## Context

When Auto-Sec acts or finds something that matters — the AI opens a draft PR, a critical/KEV finding
lands, a scan fails loud, a risk acceptance nears expiry — the team should hear about it **in
Slack**, because that's where they live (Tom's org, the first real customer, runs on it; William's
"single actionable digest, not a wall of findings" is a Slack-shaped ask). Generalized: an
**outbound delivery-channel seam** — Slack first; Teams / Discord / generic webhook later — with the
port/adapter/registry/per-workspace-connection shape ADR 0008 and ADR 0010 already proved twice.

### What exists today (grounding — read, not guessed)

**1. The notifications dispatch funnel — the ONE funnel.** The canonical path is:

- `NotificationDispatcher.dispatch()`
  (`components/notifications/infrastructure/adapters/notification_service.py::dispatch`) — "the ONLY
  sanctioned way to create `Notification` rows from other bounded contexts (enforced by
  `tests/architecture/test_notification_dispatch_rules.py`)". It applies recipient/workspace/AI
  preference filtering, then enqueues one `notifications.dispatch_notification_async` per recipient
  post-commit.
- `dispatch_notification_async` (`components/notifications/workers/tasks.py`) creates the in-app
  row, resolves the deep link into `metadata["link"]`, then runs the two channel legs:
  `_publish_created_event` (realtime WS) and **`_record_channel_deliveries`** — *the exact seam
  where a channel plugs in today*. That function consults `channels_for(recipient)` (the
  `delivery_channel_policy` gate over `UserPreference` booleans), records **`NotificationDelivery`
  ledger rows** (unique per `(notification, channel, subscription)`; conditional unique for
  subscription-NULL channels — DB-level dedup so a retried dispatch converges), and enqueues the
  per-channel sender task (`notifications.deliver_web_push`, `notifications.deliver_email`) only
  when a NEW row was recorded.
- The senders (`infrastructure/tasks/web_push_tasks.py`, `email_tasks.py`) share one discipline:
  Celery retry with backoff+jitter, per-row terminal outcomes `sent | skipped | failed`, and a
  **truthful skip** when the channel flag is off — "the ledger never claims a send that didn't
  happen."
- Channels are enumerated in `components/notifications/domain/enums.py::DeliveryChannel`
  (`realtime`, `web_push`, `email`) — "the source of truth" the ORM TextChoices align to.

The structural fact that shapes this ADR: **every existing channel is per-USER** (a user's browser,
a user's inbox), gated by that user's preferences. **Slack is per-WORKSPACE** — a team channel, not
a personal inbox. A Slack leg naively added inside the per-recipient fan-out would post the same
message once per recipient. So the funnel needs a **workspace-level external leg**, not a fourth
per-recipient channel (D1/D7).

**2. A parallel Slack notifier ALREADY exists — and it is the thing to converge, not extend.**
Shipped with roadmap #5 (outbound delivery):

- `SinkConnector` (`infrastructure/persistence/integrations/models.py`) — workspace-scoped,
  `kind = slack | webhook`, `config` JSON (`channel`, `min_severity`), `secret_ciphertext` (Fernet
  envelope via `secret_envelope_provider`), `is_enabled`, `last_delivery_at` / `last_error`.
- `AlertSinkPort` + `SlackAlertAdapter`
  (`components/integrations/application/ports/alert_sink_port.py`,
  `components/integrations/infrastructure/adapters/slack_alert_adapter.py`) — decrypts a **bot
  token**, POSTs `chat.postMessage` (plain mrkdwn text), stamps the row, never raises on expected
  failure.
- `finding_alert_delivery_handler.deliver_finding_to_slack`
  (`components/integrations/application/handlers/`) — subscribes to the shared-kernel
  `FindingRaised` (C1-clean, async via `CeleryEventPublisher`), applies the per-sink
  `min_severity` dial (`components/integrations/domain/alert_policy.py`, default `high`), and
  delivers **one message per finding event**.

Its problems are precisely the `GitHubConnection` problems ADR 0010 named: **no CRUD API, no
Settings panel** (rows are created by hand — grep confirms zero references in
`components/integrations/api/controller.py`), `Kind.WEBHOOK` is declared but has **no adapter**, and
it is **outside the funnel** — no preference model, no delivery ledger, no retry, no dedup, and a
per-event shape that means a first Prowler scan raising 400 findings ≥ the floor posts up to 400
Slack messages. Henry's constraint — *"Slack = a new delivery channel inside the one funnel, never a
parallel notifier"* — is therefore not just a design rule for new code; it is a **convergence
mandate** for this existing side-door (improve-don't-replicate: adding the productized channel is
the trigger to fix the first instance, exactly as Prowler was for the Trivy runner).

**3. The events that matter, and where they enter the funnel today:**

| Event | Emitter today | Reaches the funnel? |
|---|---|---|
| AI opened a draft PR | `open_draft_pr_use_case._notify_draft_pr_opened` → enqueues `dispatch_notification_async` directly (`notification_type="ai_event"`, workspace owner) | Yes (bypasses `dispatch()` — named drift, folded in P1) |
| Finding filed on the board | `soc_notification_signal_bridge._handle_finding_task_created` (any `ai.*` board Task) → funnel, workspace owner | Yes |
| Critical/KEV finding raised | shared-kernel `FindingRaised` (carries `severity`, `is_new`) → today only the parallel Slack handler | **No** (side-door only) |
| Scan failed loud | `cloud_posture_tasks` → `fail_job(job_id, error="scan_failed")` (BackgroundJob only) | **No** — no notification exists yet |
| Risk acceptance nearing expiry | ADR 0015 D9 P2 beat task (not built) — specced to notify on auto-reopen | Planned, via funnel |

**4. The workflow engine** (`components/workflow/domain/constants.py`,
`infrastructure/adapters/node_actions.py`): triggers include `finding_raised` /
`finding_critical` / `finding_high`; the action vocabulary has `message` (channels `email` /
`in_app` — email through the platform mailer, in-app through the funnel; **no Slack**) and
`webhook` (`_execute_webhook`) which already carries an SSRF guard —
`_assert_safe_webhook_url`: https/http only, resolve-then-deny private / loopback / link-local /
reserved / multicast, with a **documented gap** ("not hardened against DNS-rebinding… pinning the
validated IP is a tracked follow-up"). There is exactly one SSRF guard in the codebase and it lives
inside a workflow module — the new outbound path must share a hardened version of it, not grow a
second copy (D6).

**5. The payload-safety standard.** Deep-run detail (prompts, tool inputs/outputs) is **owner-only**
(`components/agents/api/controller.py` — "Full run detail (prompts, tool inputs/outputs) is
owner-only"; same rule in `deep_run_query_port.py`). Notifications deliberately carry
**notification-grade summaries + a relative deep link** (`metadata["link"]` via `link_resolver`).
Anything leaving the tenant boundary for a third-party chat service must meet the same bar or
stricter (D6).

**6. The Settings surface it joins.** `IntegrationsSection.jsx` (frontend,
`src/features/settings/presentation/sections/`) stacks the AWS connect wizard + connections list,
`LogSourcesPanel` (ADR 0008 phase 6), and `VcsConnectionsPanel` (ADR 0010 phase 3). The delivery
panel is the next card in that stack.

### The three concerns to untangle (the ADR 0008 table, third application)

| Concern | Question | Owner |
|---|---|---|
| **A. Provider integration** | *how* to deliver a message to Slack-webhook vs Slack-bot vs Teams vs a generic webhook (auth, formatting, rate limits) | **`DeliveryChannelPort` adapter** — one per provider, in `components/integrations` |
| **B. Per-workspace configuration** | *which* channels a workspace connects, their secret + event subscriptions + lifecycle | **`SinkConnector`** evolved in place (many rows per workspace) |
| **C. What / when / how safely** | which events go out, noise control, redaction, dedup, retry, ledger | **the notifications funnel** — a new workspace-level external leg (the single choke point) |

## Research grounding (claim → source)

| # | Claim | Source |
|---|---|---|
| R1 | Slack incoming webhook: one-click channel pick at authorization; the URL **is** the credential ("Your webhook URL contains a secret… Slack actively searches out and revokes leaked secrets"); no auth header; channel fixed at creation; full Block Kit | Slack docs[^slackwebhook] |
| R2 | Rate limits: ~**1 message/sec per webhook** (short bursts allowed); `chat.postMessage` special tier ~1 msg/sec/channel; 429s carry a **`Retry-After`** header that must be honored | Slack rate-limit docs[^slackrate] |
| R3 | 2025 non-Marketplace clampdown: read APIs (`conversations.history`/`replies`) cut to 1 req/min for commercially distributed unlisted apps; **posting methods unaffected**; internal apps unaffected — a warning against ever depending on read scopes without Marketplace listing | Slack changelog[^slackclamp] |
| R4 | OAuth bot mode: "Add to Slack" consent → `oauth.v2.access` → revocable bot token with rotation support; minimal scopes `chat:write` (+`chat:write.public`); the special `incoming-webhook` scope shows a channel picker at install and returns a webhook URL — an app-owned middle path | Slack OAuth + security best-practices docs[^slackoauth] |
| R5 | The vendor pattern: Snyk (legacy paste-a-webhook → Slack app; per-project `severity_threshold` + `target_channel_id`), Wiz (automation rules: severity filter → channel), Datadog (OAuth app; legacy webhooks deprecated), GitHub (per-channel subscribe w/ sane defaults + threading), PagerDuty (notification presets: Highlights/Status/All), Sentry (per-alert-rule channel). Universal knobs: **per-channel routing + a severity floor**; webhook URLs survive only as the legacy/simple path | vendor docs[^vendors] |
| R6 | Outbound-webhook reliability: exponential backoff + jitter with bounded attempts (Svix: 8 attempts over ~28h; Stripe: up to 3 days); redirects treated as failures; **auto-disable after sustained failure** (Svix: all attempts failing for 5 days) + notify the owner + manual replay | Svix retry docs, Stripe webhook docs[^reliability] |
| R7 | Idempotency: stable event IDs + a delivery record keyed by (event, destination) so retries converge; consumers tolerate duplicates; dispatch async off a queue | Stripe webhook docs[^reliability] |
| R8 | SSRF for user-supplied URLs: https-only, resolve **all** A/AAAA records and deny metadata (169.254.169.254) / loopback / RFC1918 / link-local; **pin the validated IP** for the actual request (DNS-rebinding TOCTOU); disable redirects; a strict host allowlist is the strongest posture when the destination set is known | OWASP SSRF Prevention Cheat Sheet[^owasp] |
| R9 | Slack's own app guidelines: offer **digests** rather than per-event alerts for high-volume sources, let installers set rate/channel/type preferences, batch, almost never `@channel`/`@here` | Slack planning guidelines[^slackdesign] |

## Decisions (LOCKED)

### D1 — The seam: `DeliveryChannelPort` + adapters + registry live in `components/integrations`; the trigger point is a new workspace-level external leg of the notifications funnel. No parallel notifier survives. **[locked]**

Split per the concern table. **`components/integrations` owns HOW** — it already owns every
third-party connector seam (AWS in, log sources in, VCS out), the `SinkConnector` rows, the Fernet
`secret_envelope`, and the only existing Slack adapter. `AlertSinkPort` is **renamed/generalized to
`DeliveryChannelPort`** (`components/integrations/application/ports/delivery_channel_port.py`),
shaped to the core's need — *"tell me this connection is reachable, and deliver this rendered
message to it"* — never to Slack's API:

```python
@dataclass(frozen=True)
class DeliveryHealth:
    ok: bool
    detail: str = ""                 # human-readable reason on failure (no secrets, ever)

@dataclass(frozen=True)
class DeliveryMessage:               # channel-agnostic; adapters render per target
    title: str
    body: str                        # short summary lines — already redacted (D6)
    severity: str = ""
    link: str = ""                   # absolute HUD deep link
    fields: dict = field(default_factory=dict)

class DeliveryChannelPort(ABC):
    def verify(self, connection) -> DeliveryHealth: ...      # test message / auth probe
    def deliver(self, connection, message: DeliveryMessage) -> DeliveryResult: ...
```

A **`DeliveryChannelProvider` registry** (`kind → adapter`,
`components/integrations/application/providers/`) mirrors `LogSourceProvider` / `VcsProvider`:
the composition root that knows the concrete adapters exist, resolves `secret_ciphertext` before
handing the connection to an adapter, and registers nascent adapters behind feature flags (D8).

**The notifications funnel owns WHEN/WHAT.** `NotificationDispatcher.dispatch()` gains a
workspace-level **external leg**: once per dispatch (NOT once per recipient — Slack is a team
channel, not N inboxes), post-commit, it enqueues `notifications.deliver_external` with the
`(workspace_id, event_key, summary fields, link)` tuple. That task consults the workspace's enabled
connections + subscriptions (D4), applies the noise policy (D5), records the external ledger row
(D7), and calls `DeliveryChannelPort.deliver` through the registry. Cross-context consumption is
boundary-clean: notifications imports **integrations' application port + provider** (Rule 3 allows
another context's `application.ports`; the provider is the same composition-root seam every draft-PR
consumer already uses) — never integrations' infrastructure.

Rejected placements:

- *Adapters inside notifications infrastructure* — would force notifications to import the
  `SinkConnector` model + the integrations secret envelope (a cross-context infrastructure
  coupling), and would split "connectors live in integrations" across two homes.
- *A new `delivery` bounded context* — a third silo for a concern integrations already owns half of;
  fails "unify before you multiply."
- *Keep the standalone `FindingRaised → Slack` handler and add a second funnel-driven sender* —
  exactly the parallel-notifier Henry forbade. **The existing handler is retired in P1**: finding
  alerts reach Slack through the funnel leg (per-event for singular high-signal findings, digest for
  scan batches — D4/D5). Its `min_severity` dial and `alert_policy` module are *reused* by D5, not
  discarded.

Also folded in P1: `open_draft_pr_use_case._notify_draft_pr_opened` enqueues
`dispatch_notification_async` directly, bypassing `dispatch()` — it migrates to the dispatcher so
the external leg sees every event at the one sanctioned entry.

### D2 — Per-workspace connection: evolve `SinkConnector` in place (no new model, no rename-for-taste) + a CRUD/verify API + Settings panel. **[locked]**

`SinkConnector` is already the right shape (workspace FK, `kind`, config, envelope-encrypted
secret, health stamps) — its defect is being un-productized. P1 adds columns, not a second model:

```
SinkConnector                       # infrastructure/persistence/integrations/
  workspace (FK)                    # existing
  kind        slack | webhook | teams | discord      # existing enum, extended over time (D8)
  name        "Sec-alerts (#sec-alerts)"             # existing
  auth_mode   webhook_url | bot_token                # NEW — Slack has two entry modes (D3)
  config      JSONField             # non-secret: channel label, display hints
  events      JSONField(default=DEFAULT_EVENT_KEYS)  # NEW — subscription list (D4)
  min_severity  CharField(default="high")            # NEW — promoted from config; the noise dial (D5)
  secret_ciphertext                 # existing — Fernet envelope; holds the webhook URL OR bot token
                                    #   (a webhook URL IS a bearer secret — R1 — masked in every read)
  is_enabled / status               # NEW status: connected | disabled | error (VcsConnection choices)
  last_verified_at                  # NEW
  last_delivery_at / last_error     # existing
  created_by                        # NEW (VcsConnection parity)
```

CRUD mirrors the log-source/VCS endpoints in `components/integrations/api/controller.py`:
list / create / update / delete, plus **`POST …/sinks/<id>/verify/`** which calls
`DeliveryChannelPort.verify` — for `webhook_url` mode that is a real test message ("Auto-Sec
connected ✓" with a deep link; there is no side-effect-free probe for a webhook), for `bot_token`
mode an `auth.test` + optional test message. Verify stamps `last_verified_at` / `last_error` and
sets `status`. **The secret is write-only**: responses carry a masked tail (`…/T00/B00/••••wxyz`),
never the full URL/token; `@sensitive_post_parameters` on the create/update views; the existing
`@sensitive_variables` discipline of `SlackAlertAdapter` carries over. Frontend: a
**"Notification Channels" panel** joining the `IntegrationsSection` stack beside `LogSourcesPanel` /
`VcsConnectionsPanel` (add kind → paste webhook URL → verify → toggle events), reusing the HUD
panel/card primitives.

### D3 — Phase-1 Slack mode: customer-created **incoming webhook** (new, the low-friction default) + keep the existing **bot-token** mode working; phase-2 is a proper OAuth Slack app with a channel picker. **[locked — grounded in R1–R5]**

- **Webhook (`auth_mode=webhook_url`) is the P1 default**: the customer admin creates it with the
  channel chosen at authorization time, pastes one URL — no OAuth consent screen, no app
  registration on our side, full Block Kit (R1). Snyk shipped exactly this shape for years before
  productizing an app (R5). The 1 msg/sec limit (R2) is a non-issue once bulk emissions are
  digested (D5). URL validation is a strict allowlist: `https://hooks.slack.com/services/…` — which
  also collapses the SSRF surface for this kind (D6, R8).
- **Bot token (`auth_mode=bot_token`) stays**: it exists, it works (the current adapter), and it can
  post to any channel the bot joins. Don't regress the dogfood; don't force a migration.
- **Phase 2 — OAuth Slack app** (`chat:write` + the `incoming-webhook` scope's install-time channel
  picker, or `conversations.list` for an in-HUD picker; token rotation; uninstall webhooks): the
  direction every reference vendor converged on (R5). **Marketplace listing is deferred** until we
  need read scopes or distribution — the 2025 clampdown (R3) hits read APIs on unlisted commercial
  apps, and P1/P2 posting paths are unaffected, so nothing forces the review process yet.

### D4 — Event routing: a per-connection **subscription list over a named event catalog** (sane defaults) now; a workflow `notify_external` action for advanced routing in P2 — i.e. option (c) "both". **[locked — grounded in R5]**

A pure workflow-only model (option a) would make basic Slack setup require building an automation —
too much friction for "tell me when it matters" (every vendor ships default event classes + a floor;
R5). A subscription-only model (option b) caps power users. So:

- **The event catalog** is a domain constant in notifications
  (`components/notifications/domain/…::EXTERNAL_EVENT_CATALOG` — the `EMAIL_WORTHY_TYPES` pattern,
  keyed and richer). The external leg classifies each dispatch into an `event_key` from
  `(notification_type, metadata)` — e.g. `ai_channel=action_created` + a PR link ⇒
  `draft_pr_opened`. P1 keys and **defaults (all on)**:
  - `draft_pr_opened` — the AI pushed a draft PR (the flagship "Auto-Sec acted" moment).
  - `finding_critical` — a **new** (`is_new=True`) critical finding; a KEV-flagged finding
    qualifies regardless of severity floor (D5).
  - `scan_failed` — a scan engine failed loud.
  - `scan_digest` — the per-scan summary message (D5's batch rule).
  - `risk_accept_expiring` — ADR 0015's suppress-expiry reopen (P2 there; the key is reserved now).
- **Two funnel entries must be created** for full coverage (small, named): the scanning fail-loud
  path (`fail_job(error="scan_failed")`) and scan completion currently notify no one — P1 adds a
  `system`-type dispatch from the scan pipeline (workspace owner in-app + the external leg). This
  is a root fix: operators get the in-app signal too, not a Slack-only side effect.
- **Workflow (P2)**: a `notify_external` node action joins the action vocabulary
  (`node_actions.py` registry) so playbooks can route arbitrary triggers (e.g. `finding_high` on a
  specific service) to a **named connection**. It posts **through the same funnel leg /
  `DeliveryChannelPort`** — never its own HTTP call (one canonical sender per concern; the webhook
  node stays what it is: a raw integration primitive for SOAR targets, not a notifier).

### D5 — Noise controls: severity floor + new-only gating per connection; bulk emissions are ALWAYS digested — one scan, one message. **[locked — grounded in R2/R5/R9]**

- **Severity floor**: `min_severity` per connection (default `high`), evaluated with the existing
  `alert_policy.severity_meets_threshold` — reused, not reimplemented. **KEV bypasses the floor**
  (a known-exploited vuln is never noise — the William/contextual-risk lens, ADR 0013).
- **New-only**: finding events deliver only when `is_new=True` (`FindingRaised` already carries it
  "so consumers can avoid re-alerting on steady-state noise") — re-observations never re-post.
- **The batch rule (hard)**: *a scan emitting N findings sends ONE message*, the `scan_digest`:
  "Prowler scan completed — 3 critical / 12 high / 41 medium; top 3 inline; → View in Auto-Sec."
  Per-finding external delivery is reserved for **singleton high-signal events** (a KEV/critical
  landing outside a scan batch, an attack path, a draft PR). This is Slack's own guideline (digest
  high-volume sources, batch, no `@channel`; R9), the vendor norm (R5), and it keeps us inside the
  1 msg/sec webhook budget **by construction** (R2). Mechanically: bulk scanner sources emit their
  external signal from the *scan-completed* funnel entry (D4) with aggregate counts — the external
  leg never fans out per `FindingRaised` for a source that batches.
- **Per-connection pacing**: the sender task serializes deliveries per connection and honors
  `Retry-After` on 429 (R2) — burst protection for whatever the digest rule doesn't catch.

### D6 — Payload security: notification-grade summaries + deep links ONLY; one hardened SSRF guard for every user-supplied URL. **[locked — grounded in R8 + the Option-A standard]**

- **Redaction standard** (the same Option-A line the agents surface draws — run detail is
  owner-only): an external `DeliveryMessage` carries **title, verb, severity, asset URN, counts,
  and an absolute deep link** (built from `metadata["link"]` + the frontend base URL — the funnel
  already resolves and stores the relative path). It **never** carries prompts, tool inputs/outputs,
  finding raw payloads/`attributes`, log lines, tokens, or secrets. A Slack channel's membership is
  invisible to us — treat every external message as world-readable. The rendering lives in ONE place
  (the external leg builds `DeliveryMessage`; adapters only format) so the redaction rule has one
  enforcement point, unit-tested against representative metadata.
- **SSRF**: the generic-`webhook` kind POSTs to a fully user-supplied URL from inside the cluster.
  P1 extracts the workflow engine's `_assert_safe_webhook_url` into a shared guard
  (`components/shared_kernel/…` or integrations application — one module, both callers) and
  **hardens it to the OWASP bar** (R8): https-only for delivery sinks, resolve all records and deny
  private/metadata/link-local, **pin the validated IP for the actual request** (closing the
  documented DNS-rebinding gap in the current guard — boy-scout fix for the workflow node too),
  and no redirect following. The `slack` kind doesn't need the general guard: its URL must match
  the `hooks.slack.com/services/` allowlist (R8's strongest posture) or be a `slack.com/api` bot
  call to a constant host.

### D7 — Delivery reliability: Celery-only, ledgered, retried with backoff honoring `Retry-After`, truthful skips, auto-disable on sustained failure (P2). **[locked — grounded in R6/R7]**

- **Never in-request** (perf rule §7): the external leg is enqueued post-commit; delivery happens in
  `notifications.deliver_external` on the worker.
- **`ExternalDelivery` ledger** (`infrastructure/persistence/notifications/` beside
  `NotificationDelivery`, same semantics): one row per `(sink_connector, event dedup key)` with a
  unique constraint — the DB-level idempotency that makes a retried dispatch converge instead of
  double-posting (R7; the exact `outcome.created` gate the email channel uses). Status
  `pending | sent | skipped | failed` + reason; a flag-off or unsubscribed event records `skipped`
  with a reason — the ledger never claims a send that didn't happen (house discipline).
- **Retry**: `bind=True, max_retries, retry_backoff=True, retry_jitter=True` (the
  `deliver_email` template); a Slack 429's `Retry-After` overrides the backoff (R2). Transient HTTP
  failures retry; deterministic failures (revoked URL → Slack 404 `no_service`, invalid token) mark
  the row `failed`, stamp `last_error`, and do not retry.
- **Fail loud, fail visible**: outcomes stamp `last_delivery_at` / `last_error` on the connection
  (existing adapter behavior, kept); a connection erroring persistently is visible in the Settings
  panel. **P2** adds the Svix pattern (R6): auto-`status=error`/disable after sustained failure
  (days, not minutes) + an in-app notification to admins — through the funnel, naturally.
- One dead sink never breaks another, and no delivery failure ever breaks the emitting pipeline
  (the existing port contract, kept).

### D8 — Extensibility: `kind → adapter` registry; Teams / Discord / generic-webhook slot in as adapters behind flags. **[locked]**

Adding the Nth provider = a `DeliveryChannelPort` adapter + a registry line + a `SinkConnector.Kind`
value + a frontend card — auth/formatting/rate limits are the adapter's problem; routing, noise,
redaction, ledger, retry are inherited from the funnel leg, solved once (the ADR 0008/0010
consequence, third instance). Nascent adapters register behind feature flags
(`feature.delivery_teams`, `feature.delivery_discord` — the `feature.log_source_cloudwatch`
pattern, default off, fail closed). The **generic-webhook adapter ships in P2** (its `Kind` exists
today with no implementation): JSON POST of the `DeliveryMessage` envelope behind the D6 guard —
the escape hatch for anything we haven't built (SOAR, ntfy, home-grown routers). Teams (Adaptive
Cards) and Discord are P3, demand-driven.

## Consequences

**Positive**
- Slack lands as a channel of the ONE funnel: preference-consistent, ledgered, retried, deduped,
  redacted — and every future event that enters the funnel is Slack-capable for free.
- The existing side-door notifier is converged, its flood mode (per-finding messages) is designed
  out by the digest rule, and its useful parts (`SinkConnector`, `min_severity`, the adapter's
  secret handling) are promoted, not discarded.
- Third instance of the port/registry/connection template — the seam cost keeps amortizing.
- Scan-failed and scan-completed finally notify operators in-app too (root fix, not Slack-only).
- The one SSRF guard gets hardened (IP pinning) for both its callers.

**Negative / costs**
- The funnel gains a workspace-level leg — a new concept beside the per-recipient legs (mitigated:
  same ledger/sender discipline, one new task).
- `SinkConnector` migration + CRUD + panel is real P1 surface (the price of productizing).
- Digesting requires the scan pipeline to emit completion events — a small cross-context addition
  (via the funnel, no new coupling).
- Webhook mode means customers paste bearer secrets — masked storage/display and verify-on-create
  reduce but don't eliminate mishandling risk; the P2 OAuth app is the durable fix.

## Non-goals

- Not a chat-ops / bi-directional Slack bot (no slash commands, no acting on findings from Slack —
  that's a future arm on top of the P2 OAuth app).
- Not replacing the workflow `webhook` node (raw SOAR primitive) or the `message` node's email path.
- Not per-user Slack DMs — this is a workspace/team channel; per-user channels stay
  realtime/push/email.
- No Marketplace listing in P1/P2 (R3 pressure noted; revisit when read scopes or distribution
  demand it).

## Implementation plan (each phase ships on its own; this ADR is the spec)

**P1 — webhook connection + funnel leg + default events + Settings card**
1. Rename/generalize `AlertSinkPort` → `DeliveryChannelPort` + `DeliveryChannelProvider` registry;
   `SlackAlertAdapter` → `SlackDeliveryAdapter` gaining `auth_mode=webhook_url` (Block Kit render)
   alongside the existing bot-token path; `verify()` (test message / `auth.test`).
2. `SinkConnector` migration (D2 columns) + CRUD/verify endpoints in the integrations controller +
   masked-secret DTOs.
3. The external leg: `event_key` classification + `EXTERNAL_EVENT_CATALOG` defaults (D4),
   `ExternalDelivery` ledger + `notifications.deliver_external` task (D7), redacted
   `DeliveryMessage` rendering (D6), severity floor / `is_new` / digest rules (D5).
4. Funnel entries for `scan_failed` + scan completion (`scan_digest`); migrate the draft-PR direct
   enqueue onto `dispatch()`; **retire `deliver_finding_to_slack`** (its tests move to the leg).
5. Shared SSRF guard extraction + hardening (D6); workflow webhook node switches to it.
6. Frontend: "Notification Channels" panel in `IntegrationsSection` (add → verify → event toggles →
   health), reusing HUD primitives.
7. Tests: unit (event classification, redaction, floor/digest policy, URL allowlist/SSRF guard),
   integration (CRUD + verify, ledger idempotency under retry, truthful skips, one-message-per-scan),
   architecture (notifications must not import integrations infrastructure).

**P2 — OAuth app + workflow action + digests refined**
OAuth v2 install flow + channel picker (`incoming-webhook` scope or `conversations.list`), token
rotation; `notify_external` workflow action; auto-disable on sustained failure + admin notification;
generic-webhook adapter (flagged); optional daily sub-critical digest (William's "what do I need to
know today") if operator calls validate it.

**P3 — more providers**
Teams (Adaptive Cards) / Discord adapters behind flags; per-event-class presets (PagerDuty-style) if
subscription lists prove too coarse; quiet hours for digest-class messages only (never critical).

## Open questions (for Henry)

1. **Digest cadence beyond per-scan**: is a daily "what do I need to know today" Slack digest (the
   Tom/William convergence) wanted in P1, or validate with them first? (P1 ships per-scan digests
   only; the daily digest is one more `event_key` when wanted.)
2. **Multiple channels per workspace at P1**: the model supports many connections (e.g.
   `#sec-critical` floor=critical + `#sec-all` floor=high). Ship the multi-row UI in P1, or one
   connection first and grow the panel?
3. **Bot-token mode longevity**: after the P2 OAuth app lands, do we keep raw bot-token entry
   (self-hosters / air-gapped Slack Enterprise?) or deprecate it like Datadog did its webhooks?
4. **`@here` on KEV/critical**: Slack guidelines say almost never — but a KEV on an exposed asset is
   arguably the "almost". Default off; per-connection opt-in toggle worth it?
5. **Naming**: keep `SinkConnector` (shipped name) or rename to `DeliveryConnection` in the D2
   migration while it's still hand-created-only (zero API consumers today — the cheap moment)?

[^slackwebhook]: Slack docs, *Sending messages using incoming webhooks* — URL contains a secret; channel fixed at creation; Block Kit support. https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks
[^slackrate]: Slack docs, *Rate limits* — ~1 msg/sec per webhook with burst allowance; `chat.postMessage` special tier ~1 msg/sec/channel; 429 + `Retry-After`. https://docs.slack.dev/apis/web-api/rate-limits
[^slackclamp]: Slack changelog 2025-05-29 / 2025-06-03 — non-Marketplace commercial apps: read-API clampdown; posting methods unaffected. https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/ ; https://docs.slack.dev/changelog/2025/06/03/rate-limits-clarity/
[^slackoauth]: Slack docs, *Installing with OAuth* + *Best practices for security* — `oauth.v2.access`, token rotation/revocation, least-privilege scopes, `incoming-webhook` scope channel picker. https://docs.slack.dev/authentication/installing-with-oauth ; https://docs.slack.dev/authentication/best-practices-for-security
[^vendors]: Snyk *Slack app* / *SlackSettings API* (severity_threshold, target_channel_id) https://docs.snyk.io/integrate-with-snyk/jira-and-slack-integrations/slack-app ; Wiz Slack integration https://www.wiz.io/integrations/slack ; Datadog Slack integration https://docs.datadoghq.com/integrations/slack/ ; GitHub Slack app https://github.com/integrations/slack ; PagerDuty Slack guide https://support.pagerduty.com/main/docs/slack-integration-guide ; Sentry Slack https://docs.sentry.io/organization/integrations/notification-incidents/slack/
[^reliability]: Svix, *Retry schedule* — backoff schedule, redirects = failure, auto-disable after 5 days of failure + notify + replay. https://docs.svix.com/retries ; Stripe, *Webhooks* — retries up to 3 days, stable event IDs, duplicate tolerance, async consumption. https://docs.stripe.com/webhooks
[^owasp]: OWASP, *Server-Side Request Forgery Prevention Cheat Sheet* — scheme/host validation, deny private + metadata ranges on ALL resolved records, pin validated IP (DNS rebinding), disable redirects, allowlist when destinations are known. https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
[^slackdesign]: Slack, *App design guidelines / planning* — digest high-volume notifications, installer-set preferences, batch, avoid `@channel`/`@here`. https://api.slack.com/start/planning/guidelines ; https://docs.slack.dev/concepts/app-design/
