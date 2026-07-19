# Auto-Sec POC — AWS CloudTrail → Detect → Triage → Slack/HUD (plan)

**Status:** approved direction, awaiting 4 inputs (see §12) · **Date:** 2026-07-17
**Goal:** a demoable proof that auto-sec ingests a real org's AWS activity, detects
risky events, has an AI agent triage + assign them to a SOC member on the Kanban,
and alerts Slack + the command-center HUD. Target audience: design partners /
investors.

Grounded in three research passes (AWS ingestion; AI-SOC triage + detection
engineering; integration/connector + Slack + secrets) — citations inline.

---

## 1. Verdict + first principles

The core call — **integrations/data FIRST, then the agent** — is correct and
research-backed. An agent with no data is a demo of nothing. So the data plane is
the foundation; the triage agent is a *consumer* of it.

Three decisions locked (all industry-standard):
1. **CloudTrail is the first source**, not GuardDuty. CloudTrail is the "who did
   what" truth (root logins, MFA, SCP changes). GuardDuty is findings-only, costs
   money, and is a *later enrichment* source.
2. **Read CloudTrail from an S3 bucket**, not a direct CloudTrail hook. This is
   exactly how log-ingestion vendors (Panther, Sumo Logic) onboard AWS — narrow
   **S3 read** on the log bucket — vs posture vendors (Vanta/Wiz) who grab broad
   `SecurityAudit`. Auto-sec is log-ingestion.
3. **Onboard via the Vanta model** — a cross-account IAM role the customer runs in
   their AWS via a one-click CloudFormation "Launch Stack", trusting our account
   with a **per-customer ExternalId**. Self-serve, no scripts from us.

**The load-bearing architectural rule (from the AI-SOC market):** *deterministic
rules FIRE the alert; the LLM only investigates downstream.* Never run an LLM over
the raw log firehose — it's expensive and prompt-injectable by attacker-controlled
log content. The agent's job is **triage**, not detection.

---

## 2. Architecture

```
[AWS source integration]  cross-account assume-role → read CloudTrail from the
        │                 customer's S3 bucket (per-tenant role ARN + ExternalId)
        │  parse Records[], dedupe on eventID
        ▼
[Normalize → SecuritySignal]  OCSF-*shaped* subset (actor, src_ip, event_class,
        │                     metadata, raw) — NOT full OCSF (see §3)
        ▼
[Deterministic rule engine]  Sigma-mapped rules, each tagged with a MITRE technique
        │  → fires a Detection (severity + technique_id + observables)
        ▼
[Triage agent — single agent + MCP tools]  enrich → verdict + reasoning chain →
        │  assign to a SOC team member on the Kanban
        ▼
[Sinks]  Slack App (Block Kit card w/ Ack/Assign) + command-center HUD
         (Detections hex glows; card lands on the triage board)
```

Everything is a **connector** in a registry (§9): sources implement an ingest
port, sinks a deliver port — the "import/output" framing.

---

## 3. Data model (OCSF-shaped subset — not full OCSF)

Full OCSF is 2–4 months of work + ongoing schema-drift tax. Adopt an **OCSF-shaped
subset** so migration (and AWS Security Lake portability) is cheap later, without
paying the mapping cost now. Always retain `raw`.

- **SecuritySignal** (normalized event): `time`, `event_class` (Authentication /
  API-Activity / Network-Activity / base), `activity`, `severity_id`,
  `actor` (principal ARN / type / account), `src_ip`, `metadata`
  (product/vendor/source id — provenance), `message`, `raw`.
- **Detection** (a rule): `key`, `title`, `technique_id` (MITRE), `severity`,
  `source`, enabled.
- **Signal/Alert** (a detection firing on signals): `severity`, `mitre_technique`,
  observables (IP, principal ARN, resource), `status`, `assignee`.
- **Case/Incident** (correlated alerts): assignee, status, timeline, **verdict**.
- **Triage result** (attached to the case): `verdict`
  (`Actionable` / `Benign-Positive` / `False-Positive` / `Undetermined`),
  `confidence`, `reasoning_chain`, `recommended_action`.

Present the AI investigation as **verdict + confidence + step-by-step reasoning
grounded in tool outputs + raw evidence** — explainability is what every credible
vendor ships and what defeats the "black-box" anti-pattern that *increases* MTTR.

New bounded context: `components/detection/` (signals, detections, rule engine) +
reuse `components/agents/` (triage), `components/project/` (Kanban), `sign_off`,
`audit`, `notifications`. New persistence app: `infrastructure/persistence/detection/`.

---

## 4. The 5 starter detections (MITRE-mapped, exact CloudTrail fields)

Seed from open rulesets (SigmaHQ `rules/cloud/aws/cloudtrail/`, Panther, Elastic) —
don't hand-write. Each rule is deterministic, cheap, unit-testable.

| # | Detection | MITRE | CloudTrail match |
|---|---|---|---|
| 1 | Root console login | T1078.004 | `eventName=ConsoleLogin`, `userIdentity.type="Root"`, `responseElements.ConsoleLogin="Success"` |
| 2 | Console login without MFA | T1078.004 | `eventName=ConsoleLogin`, `additionalEventData.MFAUsed="No"` |
| 3 | CloudTrail tampering | T1562.008 | `eventSource=cloudtrail.amazonaws.com`, `eventName∈{StopLogging,DeleteTrail,UpdateTrail}` |
| 4 | Interactive session via SSM | — (access) | `eventSource=ssm.amazonaws.com`, `eventName=StartSession`, `requestParameters.target="i-…"` |
| 5 | SCP / Org policy change | T1098 / evasion | `eventSource=organizations.amazonaws.com`, `eventName∈{Create,Update,Delete,Attach,Detach}Policy`; SCP-only via `requestParameters.type="SERVICE_CONTROL_POLICY"` |

**Three gotchas so the demo doesn't lie:**
- **Raw SSH to EC2 is NOT in CloudTrail** (not an API call). Detect **SSM
  `StartSession`** (the modern shell-in path). Even commands *inside* an SSM
  session aren't in CloudTrail — only the `StartSession`.
- **SSO logins show `MFAUsed="No"`** even when the IdP enforced MFA — only IAM/root
  MFA sets it. Don't flag SSO on `MFAUsed=="No"` alone; detect SSO via
  `userIdentity.type` (`SAMLUser` / `IdentityCenterUser`).
- **`sourceIPAddress` is sometimes a DNS name / "AWS Internal"**, not an IP — guard
  the geo/IP parser or it false-positives.

---

## 5. AWS ingestion (the source adapter)

**Onboarding (self-serve, Vanta/Panther pattern):**
1. Auto-sec generates a **per-customer ExternalId (UUID)** the customer can't
   choose.
2. Render a CloudFormation **"Launch Stack"** quick-create URL
   (`…/cloudformation/home#/stacks/create/review?templateURL=<s3>&param_ExternalId=<uuid>`).
3. The stack creates a cross-account role trusting our account with
   `Condition StringEquals sts:ExternalId=<uuid>`, granting **prefix-scoped S3
   read** on the CloudTrail bucket (+ `kms:Decrypt` if SSE-KMS — and the CMK key
   policy must *also* authorize the role; KMS is default-deny).
4. Customer returns the **Role ARN**. **Before storing, test-assume WITH and
   WITHOUT the ExternalId** — if it assumes *without*, the trust policy is
   misconfigured; refuse to store (37% of vendors get this wrong).

**Minimal read IAM policy:** `s3:ListBucket` (bucket ARN, `s3:prefix` scoped to
`AWSLogs/<acct>/CloudTrail/*`) + `s3:GetObject` (object ARN) + `s3:GetBucketLocation`
(+ `kms:Decrypt`/`DescribeKey` if encrypted).

**Ingest:** read the customer's existing CloudTrail S3 bucket — **push, not poll**:
subscribe SQS to CloudTrail's SNS "new log file" notification (or `s3:ObjectCreated`
→ SQS). For the weekend slice, a **Celery-beat S3 poller** is fine. Parse the
gzipped `Records[]` array, **dedupe on `eventID`** (duplicates happen). Latency is
CloudTrail's own ~5 min (best-effort, no SLA) — acceptable.

*Not* EventBridge (needs per-account/region setup in every customer account), *not*
CloudTrail Lake ($0.75/GB — non-starter for a POC), *not* LookupEvents (2 req/s,
90-day, management-events-only — backfill only).

**Multi-tenant creds:** store per-tenant `{role_arn, external_id}`; `sts:AssumeRole`
at access time; **cache temp creds until ~5 min before expiry**; set a
`RoleSessionName` encoding the tenant (appears in the *customer's* CloudTrail = their
audit hook). Never persist the returned temp credentials.

---

## 6. Triage agent (single agent + tools — NOT multi-agent yet)

Consensus: **start single-agent + typed tools; graduate to supervisor + sub-agents
only when complexity/compliance demands it.** A multi-agent run is ~3.4× the
latency — bad for a snappy demo.

- **One triage agent** (reuse `components/agents/`), runs **per fired detection**
  (never per raw event): plan → gather evidence → verdict + confidence + reasoning
  chain → assign to a Kanban member (reuse the existing `create_task` /
  `assign_task` tools) → notify.
- **Typed tools / MCP** for enrichment, each returning JSON so reasoning is
  auditable: AWS lookups (IAM/CloudTrail context), IP reputation, identity/user
  context, geo-velocity.
- **Risk classification is DETERMINISTIC (rules, not an LLM)** — for a product
  ingesting attacker-controlled data, an LLM classifier is prompt-injectable. The
  LLM is at most an input the rules re-check.
- **Dangerous actions gated by `sign_off`** — irreversible/offensive actions
  (containment, teardown) require human approval regardless of the agent's caps;
  the delegated cap is a ceiling, the offensive-action policy is a floor. (Ties to
  the RBAC/agent-principal model in `PERSONA_ROLE_RBAC_MODEL_2026-07-17.md`.)
- **Document** the supervisor + sub-agent upgrade path (don't build it) — shows the
  frontier without over-engineering.

---

## 7. Sinks

- **Slack — a real Slack App** (bot token + `chat.postMessage` + **Block Kit**),
  NOT an incoming webhook (webhooks can't do Ack/Assign buttons or `chat.update`
  the message). Post an alert card with **Acknowledge** / **Assign** buttons;
  on click, Slack POSTs to our interactivity URL → verify signature, reply 200
  within 3s, then `chat.update` to "Acknowledged by @X". Self-connect per org via
  OAuth v2 ("Add to Slack"), store the `xoxb-` token per `team.id`. Queue outbound
  at **≤1 msg/sec/channel** (coalesce alert storms — treat suppression as a
  feature).
- **Command-center HUD** — the Detections hex glows on a new detection; the triage
  card lands on the Kanban board (already wired: task-count rise → hex glow).

---

## 8. Safe demo — Stratus Red Team + replay (the unlock)

**Stratus Red Team** (Datadog, "Atomic Red Team for cloud") generates the exact
CloudTrail events safely — warm-up → detonate → **cleanup**. Techniques mapping to
our 5 detections: `aws.initial-access.console-login-without-mfa`,
`aws.defense-evasion.cloudtrail-stop` / `-delete`, `aws.persistence.iam-create-admin-user`,
`aws.credential-access.ssm-retrieve-securestring-parameters`, etc.

- **Stratus makes REAL API calls → use a THROWAWAY sandbox AWS account, never the
  work account.**
- **For the pitch:** run Stratus **once**, record the CloudTrail JSON, and
  **replay** the events into auto-sec's normalize stage — **zero live AWS on stage**,
  fully deterministic and repeatable.

---

## 9. Integration model (source/sink connector registry)

Copy Panther's split: **Connector** (registry row) + **Transport** + **Schema**.

- `Connector`: `direction` (INPUT|OUTPUT), `kind` (aws_cloudtrail / slack / …),
  `transport`, `config` (JSON), `secret_ref` (pointer, not the secret), `status`,
  `last_checked_at`.
- INPUT connectors implement an **ingest port**; OUTPUT connectors a **deliver
  port** — one adapter per kind, behind the port (fits our hex architecture).
- **Connection health:** periodic `sts:AssumeRole` probe → `connected /
  needs-attention / error` + a "re-validate" action (Datadog Issues-tab pattern).
- Roadmap sources after AWS+Slack: GuardDuty (enrichment), Okta/identity, GitHub
  audit, then **SIEM sources** (Datadog / Splunk / ELK) as *alternative inputs* —
  an org that already centralizes logs lets auto-sec read *from the SIEM*.

**Secrets:** POC = **Fernet field encryption with a KMS-wrapped key** (use
maintained `django-fernet-fields-v2`, not the abandoned original). Graduate to
**KMS envelope encryption with a per-tenant data key + `tenant_id` encryption
context** (cryptographically binds ciphertext to the tenant). Secrets Manager only
for a bounded set of high-value creds ($0.40/secret/mo doesn't scale per-tenant).

---

## 10. Phased build (honest split — no bandaids)

**Phase 0 — Weekend slice (proves the concept end-to-end):**
- Operator wires the assume-role **once** for a **sandbox AWS** (same
  `sts:AssumeRole` mechanism, operator-configured — *not* the self-serve UI yet).
- S3 CloudTrail poller (Celery beat) → parse `Records[]` → dedupe → normalize to
  `SecuritySignal`.
- The **5 deterministic rules** → `Detection` (MITRE-tagged).
- **Triage agent** files a severity-tagged **Kanban card** assigned to a SOC member.
- **Slack alert** (Block Kit) + **Detections hex glows**.
- Driven by **Stratus + recorded-event replay**.
- *This is the demo.*

**Phase 1 — Self-serve onboarding (productization, NOT throwaway):**
- The CloudFormation "Launch Stack" wizard + ExternalId + test-assume-both-ways +
  connection-health — a genuine additive layer on the *same* assume-role adapter.

**Phase 2 — Push ingestion + more sources:** SNS/SQS-on-delivery; GuardDuty
enrichment; Okta/GitHub; SIEM-as-source.

**Phase 3 — Triage depth:** MCP enrichment tools, geo-velocity, supervisor +
sub-agents if false-positive rate demands it.

> The weekend/Phase-1 split respects no-shortcuts: the manual role wiring is the
> **identical** `sts:AssumeRole` path, just operator-configured instead of a wizard.
> Phase 1 adds UI on top; it reworks nothing.

---

## 11. What NOT to do
- Don't put an LLM in the detection path / over the raw firehose.
- Don't start with GuardDuty (findings-only, costs money) — CloudTrail first.
- Don't build full OCSF now (OCSF-shaped subset only).
- Don't build the multi-agent fleet for the POC (single agent + tools).
- Don't run Stratus in a real/work AWS account (throwaway only).
- Don't use a Slack incoming webhook (can't do interactive Ack/Assign).

---

## 12. Open inputs before starting
1. **Sandbox AWS account** for the demo (throwaway — Stratus makes real API calls),
   *or* run purely on **recorded/replayed** CloudTrail (no live AWS at all)?
2. **Slack workspace** for the alert demo.
3. **"Sanctuary"** — did you mean **Sysdig**, or a specific SIEM you use?
   (Datadog/Splunk/ELK fit as alternative inputs in Phase 2.)
4. Confirm the **Phase-0 weekend scope** — then I start with the CloudTrail source
   adapter + rule engine (the data plane), the foundation everything hangs off.

## References
- AWS: cross-account role + ExternalId (confused-deputy), CloudFormation quick-create / StackSets, CloudTrail S3 delivery + SNS notifications, record-contents / userIdentity / sign-in-events schema, SSM CloudTrail logging, KMS envelope + encryption context, STS AssumeRole, Well-Architected SEC03-BP09 + Agentic-AI-Lens AGENTSEC04-BP02.
- Detection: SigmaHQ AWS CloudTrail rules, Panther / Elastic / Falco rulesets, MITRE T1078.004 / T1098 / T1136.003 / T1562.008, Stratus Red Team technique catalog.
- AI-SOC: SACR AI-SOC landscape, Dropzone/Prophet/Radiant/Charlotte, UnderDefense best-practices, CORTEX (multi-agent evidence).
- Integration/Slack/secrets: Panther connector model, OCSF (schema.ocsf.io / Security Lake), Slack Block Kit / chat.postMessage / OAuth v2 / rate limits, django-fernet-fields-v2, AWS KMS data keys.
</content>
