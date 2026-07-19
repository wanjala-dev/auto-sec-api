# Integrations Subsystem — AWS-first (POC → enterprise)

Status: **PLAN / not started** · Owner: Henry · Created: 2026-07-17

## Context — why this exists

Auto-Sec (autosec) is a SOC/SIEM product. To detect anything real it must **hook into the
customer's cloud** and read their security telemetry. Two forcing functions:

1. **POC / demo.** Henry wants to demo a real detection to security friends + former directors: the
   system watches an AWS environment (CloudWatch / GuardDuty / etc.) in the background, and when an
   anomaly lands, the dashboard's **Alerts node glows** (that glitch-pulse already exists) and a
   triage agent surfaces root-cause context. Henry has a live AWS account to test against.
2. **Enterprise reality.** Any org we sell to already runs AWS/GCP/Azure. Onboarding = "connect your
   cloud." So we need a first-class **Integrations** surface (a Settings ▸ Integrations card) where
   an operator adds a cloud account, and a provider-agnostic connector layer behind it.

**AWS first** (Henry's test env + GuardDuty is the richest low-effort source). GCP/Azure are the
same shape later — this plan builds the seam so they plug in.

This connects to the agent roster (see `docs/plans/` agent plan, TBD): the connector emits
normalized findings → the **triage agent** consumes them. Integrations produce the signal; agents
reason over it.

## Non-negotiable: security posture

This is security software; the integration path is the highest-value attack surface. Rules:

- **No long-lived cloud keys.** AWS connection uses a **read-only cross-account IAM role** the
  customer creates; we assume it via STS with an **ExternalId** (prevents the confused-deputy
  problem). Never store the customer's access keys.
- **Least privilege.** The role's policy is read-only and scoped to the telemetry APIs we use
  (GuardDuty/SecurityHub/CloudTrail/CloudWatch Logs read). We publish the exact policy; we never ask
  for `*`.
- **Secrets encrypted at rest.** Role ARN is not secret, but the ExternalId + any tokens are stored
  encrypted (Django field encryption / KMS-style), never logged. Reuse the repo's PII-safe logging
  rules — connection events log `workspace_id`/`account_id`, never secrets.
- **Every connection change is audited** (reuse `components/audit`) and gated behind **sign-off**
  (`components/sign_off`) for destructive actions (disconnect, scope change).
- **Feature-flag gated** (`feature.integrations`) while in development, off in prod by default,
  enabled per pilot workspace (the existing scope-freeze pattern).
- **Read-only for the POC.** No write-back to the customer's AWS (no remediation actions) until a
  later, explicitly-approved phase with its own guardrails.

## Architecture — a new bounded context

New Explicit-Architecture context: **`components/integrations/`** (mirrors the canonical structure
in `.claude/rules/bounded-context-structure.md`). Persistence in
`infrastructure/persistence/integrations/`.

```
components/integrations/
  api/            controller.py, urls.py, requests/, resources/   (Settings surface + status)
  application/
    ports/        cloud_connector_port.py, telemetry_source_port.py, secret_store_port.py
    use_cases/    connect_aws_account_use_case.py, poll_findings_use_case.py,
                  test_connection_use_case.py, disconnect_integration_use_case.py
    providers/    integration_provider.py         (wires port -> adapter per provider)
    handlers/     finding_ingested_handler.py     (emits to dashboard feed + fires triage agent)
  domain/
    entities/     cloud_account_entity.py, security_finding_entity.py
    value_objects/ provider.py (AWS|GCP|AZURE), finding_severity.py, connection_status.py
    events/       cloud_account_connected.py, security_finding_ingested.py
    policies/     least_privilege_policy.py
  infrastructure/
    adapters/aws/ aws_sts_assume_role_adapter.py, guardduty_source_adapter.py,
                  securityhub_source_adapter.py, cloudtrail_source_adapter.py
    repositories/ cloud_account_repository.py, security_finding_repository.py
    tasks/        poll_aws_findings_task.py        (Celery beat — assume role, pull, normalize)
  mappers/db/, mappers/rest/
```

### Ports (the seam that makes GCP/Azure drop in)
- **`CloudConnectorPort`** — `test_connection(account)`, `assume(account) -> creds`. AWS adapter uses
  STS AssumeRole + ExternalId. GCP adapter (later) uses workload-identity federation; Azure uses an
  app registration. The application core never sees provider SDKs.
- **`TelemetrySourcePort`** — `fetch_findings(account, since) -> [SecurityFinding]`. One adapter per
  source (GuardDuty first). Normalizes provider findings to the domain `SecurityFinding` (id,
  source, severity, title, resource, first_seen, raw). This is the "arm contract" output schema —
  every source emits the same `SecurityFinding` so the dashboard + agents are source-agnostic.
- **`SecretStorePort`** — encrypted storage for the ExternalId / any tokens.

### Data model (persistence)
- `CloudAccount` — workspace FK, provider, external account id, role ARN, external_id (encrypted),
  region(s), status (pending/connected/error), last_polled_at, scopes. Unique per (workspace,
  provider, account_id).
- `SecurityFinding` — workspace FK, cloud_account FK, source (guardduty/securityhub/…), external
  finding id (idempotency), severity, title, resource, status (new/triaged/…), first_seen,
  last_seen, raw JSON, triage_verdict (nullable, filled by the agent). Indexed for the dashboard
  feed query.

### Data flow (POC path)
```
Operator connects AWS (Settings ▸ Integrations)
  → CloudAccount(status=pending) + generated trust policy shown to operator
  → operator creates the read-only role in their account, pastes role ARN
  → test_connection (STS AssumeRole + a harmless read) → status=connected  [+ audit event]

Celery beat: poll_aws_findings_task (every ~1–2 min per connected account)
  → assume role → GuardDutySourceAdapter.fetch_findings(since=last_polled_at)
  → normalize → upsert SecurityFinding (idempotent on external id)
  → emit SecurityFindingIngested (shared_kernel event)
     → dashboard alert feed (Channels/websocket or poll) → Alerts node GLOWS
     → triage agent fires (deep-run) → writes triage_verdict back onto the finding
```

## Frontend — Settings ▸ Integrations

A Settings surface (new nav entry) with an **Integrations card grid**: AWS (active), GCP / Azure
(coming soon). AWS card flow:
1. "Connect AWS" → modal: enter Account ID + region(s).
2. We show the **exact read-only IAM policy + trust policy** (with the generated ExternalId) to
   paste into a CloudFormation quick-create / the IAM console.
3. Operator pastes the created **Role ARN** → "Test connection" → status chip (Connected / Error).
4. Connected card shows: last poll time, findings count, source toggles (GuardDuty on; SecurityHub /
   CloudTrail later), Disconnect (sign-off gated).

Reuse the V2 HUD styling (HudPanel/HudButton/HudText); no hand-rolled cards. This is the card Henry
asked for ("a Settings page/card where we can add integrations").

## POC demo reliability

Build the **real** AWS connector (no fake success states — per no-shortcuts). BUT seed a small set
of **real sample GuardDuty findings** (`seed_demo_findings` management command) so the dashboard has
signal to show and the glow/triage demo works even when not pointed at a live account. The demo
script: red-team persona logs in → dashboard → a seeded/real GuardDuty anomaly lands → Alerts node
glitches → click → triage agent verdict + recommended containment.

## Phasing

- **Slice 1 (POC spine, recommended first):** `integrations` context + `CloudAccount`/`SecurityFinding`
  models + AWS STS AssumeRole adapter + GuardDuty source adapter + poll task + Settings ▸
  Integrations connect flow + `SecurityFindingIngested` → dashboard feed + glow. Seed sample
  findings. (No agent yet — proves the pipe end-to-end.)
- **Slice 2:** wire the **triage agent** (LangGraph specialist, one tuned prompt via the prompt-eval
  harness) onto `SecurityFindingIngested`; write `triage_verdict` back; surface it on click.
- **Slice 3:** add SecurityHub + CloudTrail/CloudWatch sources behind the same `TelemetrySourcePort`.
- **Slice 4:** GCP + Azure connectors (same ports); provider card grid fills in.
- **Later (gated):** write-back/remediation actions (blue-team agent) — separate approval + guardrails.

## Open questions / inputs needed

- **AWS test account + region** to point Slice 1 at (Henry's env).
- Do we want the CloudFormation **quick-create stack** link for role setup (best UX) or manual IAM
  console paste for the POC? (Recommend: manual for Slice 1, quick-create in Slice 3.)
- Encryption backend for the ExternalId (Django-encrypted-fields vs. app-level KMS) — pick one.
- Polling cadence + GuardDuty API cost/limits at demo scale (cheap; findings API is light).

## References

- Agentic-SOC pattern (orchestrator + detection/triage/intel/response specialists): Google Cloud
  "Orchestrate security ops with agentic AI", EY "Agentic SOC", Conifers "Top AI SOC agents 2026".
- AWS telemetry: GuardDuty (ML anomaly findings; consumes CloudTrail/VPC Flow/DNS), Security Hub
  (aggregates + prioritizes), CloudTrail (API audit). Cross-account via read-only role + ExternalId.
- Internal: `.claude/rules/bounded-context-structure.md`, `architecture-manifesto.md`,
  `logging.md` (PII-safe), the `agents` framework (`components/agents/.../langchain/base.py`,
  `deep/`), the prompt-eval harness (`components/agents/tests/prompt_eval`, `eval_example` store).
```
