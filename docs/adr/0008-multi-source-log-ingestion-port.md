# ADR 0008 — Multi-Source Log Ingestion behind a `LogSourcePort`

Status: Proposed (2026-07-30)
Relates to: ADR 0004 (CNAPP spine — rule **C5** "ports fit the core, not the tool"), ADR 0006
(`ScannerPort` / `ScanExecutionBackend` — the same driven-adapter-behind-a-port precedent), and the
dogfood log pipeline (`components/integrations/application/log_ingest_service.py`).

## Context

Auto-Sec ingests logs to drive the HUD LOG STREAM card, the logwatch error detector, the temporal
pattern analyzer, and the per-region map drill. Today that ingestion is **hard-wired to one source**:
Amazon S3, read via a `trail_s3_bucket` / `trail_s3_prefix` pair **bolted onto the AWS
organization connection** (`AwsOrganizationConnection`). The read path assumes the customer role and
lists/gets/gunzips objects under that prefix.

Two things forced this ADR:

1. **A regression exposed the fragility.** The demo's `trail_s3_bucket` was silently blanked when the
   AWS connection was re-verified (the create/reconnect request defaults the field to `""`), so the
   log stream went quiet with no error — see the dogfood-log-pipeline note. The *symptom* fix is to
   restore the field; the *root* problem is that log configuration is an ad-hoc attribute of an
   unrelated connection, with no lifecycle of its own.
2. **S3 is one source among many.** Real workspaces ship logs from **CloudWatch Logs, Datadog,
   Splunk, syslog, HTTP webhook, GCS/Azure Blob** — and, because of **data residency**, often from
   **several sources at once** (each regionalized app ships to its own sink). A single
   `trail_s3_bucket` field cannot express "this workspace has an S3 trail in us-east-1 **and** a
   Datadog site in the EU **and** a Splunk index on-prem."

The conversation kept conflating three separate concerns. Untangling them is the decision (cf. ADR
0006's concern table):

| Concern | Question | Owner |
|---|---|---|
| **A. Source integration** | *how* do we read from S3 vs CloudWatch vs Datadog vs Splunk (auth, paging, format) | **`LogSourcePort` adapter** — one per source kind |
| **B. Per-workspace configuration** | *which* sources a workspace runs, their config + secrets + lifecycle | **`WorkspaceLogSource`** model (many rows per workspace) |
| **C. Ingest pipeline** | read a window, dedupe, checkpoint, normalize, detect, aggregate | **source-agnostic ingest service** (today's `log_ingest_service`, generalized) |

### Grounding (research)

- **In-repo precedent — `ScannerPort` (ADR 0004/0006).** Prowler and Trivy are driven adapters behind
  one port shaped to the core's need (`scan()→NormalizedFinding`), never to a tool's CLI. Rule C5:
  "adding a pillar is a new adapter, never a new pipeline." **Log sources are the identical shape** —
  a source is a *tool the app drives* to produce records.
- **In-repo precedent — payment gateways (the multi-tenant, multi-provider template).** A
  `PaymentProvider` **catalog** (slug + `config_template` describing the fields to collect) + a
  `WorkspacePaymentMethod` **per-workspace concrete config** (many active at once), selected through a
  `PaymentGatewayProvider` **slug→adapter registry** with health/fallback. This is exactly the
  "let a workspace configure whatever they like, or several at once" shape we need.
- **Industry — pluggable receivers are the universal pattern.** The
  [OpenTelemetry Collector](https://signoz.io/comparisons/opentelemetry-collector-vs-fluentbit/)
  models input as **receivers**, [Fluent Bit](https://www.parseable.com/blog/otel-collector-vs-fluentbit)
  as **input plugins** (800+), [Datadog Cloud SIEM](https://docs.datadoghq.com/security/cloud_siem/guide/setting-up-security-monitoring-for-aws/)
  as connectors normalized by its OCSF Processor, and
  [AWS→SIEM](https://repost.aws/articles/ARovkGt56ASUausPgDkr2kPg/how-to-forward-application-logs-from-aws-to-any-siem-platform)
  guidance routes many sources into one pipeline. Both **pull** (S3/CloudWatch pollers) and **push**
  (Lambda/webhook stream) coexist; every source normalizes to a common record.

## Decision

Introduce **`LogSourcePort`** — a driven-adapter seam so *how* a source is read is swappable and
composable per workspace — plus a **`WorkspaceLogSource`** per-workspace config model and a
**`LogSourceProvider`** registry. This is `ScannerPort`/`PaymentGateway` applied to log inputs. All of
it lives in **`components/integrations`** (which already owns the AWS connection, `log_ingest_service`,
and the pattern analyzer). `LogSourcePort` is an **integrations-internal** port (only integrations
implements + consumes it) — unlike `ScannerPort` it does not go in the shared kernel.

```
 WorkspaceLogSource rows              LogSourceProvider (registry: kind → adapter)
 (per workspace, MANY at once)   ┌────────┬────────────┬────────────┬───────────┐
  kind / config / secrets /      ▼        ▼            ▼            ▼           ▼
  status / cursor           S3LogSource  CloudWatch   Datadog      Splunk    (webhook…)
        │                        └──────── all implement LogSourcePort ───────┘   ← driven adapters
        │  enabled sources            │ verify(config) → health
        ▼                             │ read_window(config, since) → (LogRecord[], cursor)
  source-agnostic ingest  ───────────┘
  (checkpoint · dedupe · normalize · detect · aggregate)
        ▼
  HUD LOG STREAM · logwatch detector · temporal pattern analyzer · per-region map drill
```

### D1 — `LogSourcePort` (application/ports/log_source_port.py)

Shaped to the core's need — *"tell me you're reachable, and give me the next window of normalized
records"* — not to boto3 / the Datadog SDK / the Splunk REST API.

```python
@dataclass(frozen=True)
class LogSourceHealth:
    ok: bool
    detail: str = ""            # human-readable reason on failure (no secrets)

@dataclass(frozen=True)
class LogWindow:
    records: tuple[LogRecord, ...]
    cursor: str = ""            # opaque per-source checkpoint (S3 key, CW nextToken, DD/Splunk time)

class LogSourcePort:
    def verify(self, config: dict) -> LogSourceHealth: ...
    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow: ...
```

`config` is the per-kind opaque dict from `WorkspaceLogSource.config` (already secret-resolved by the
provider). `cursor` generalizes the existing `IngestCheckpoint` so re-reads are idempotent and each
source advances independently.

### D2 — `LogRecord` gains source identity (normalization)

The existing `LogRecord` (`service`, `level`, `message`, `raw`, `ts`) is the normalized shape. Add
`source_kind` (`"s3" | "cloudwatch" | "datadog" | "splunk"`) and `source_id` (the `WorkspaceLogSource`
id) so a merged, multi-source stream self-identifies — the HUD/map can group or filter by source.
Adapters own the mapping from their native shape into `LogRecord` (the S3 adapter keeps the
`attrs.com.docker.compose.service` extraction; CloudWatch maps `logStreamName`; Datadog maps
`service`/`status`; Splunk maps `sourcetype`).

### D3 — `WorkspaceLogSource` model (per-workspace, MANY at once)

`infrastructure/persistence/integrations/`:

```
WorkspaceLogSource
  workspace (FK)            # owner
  kind        s3 | cloudwatch | datadog | splunk | webhook
  name        "prod us-east-1 trail"     # operator label
  config      JSONField                  # per-kind: {bucket,prefix,role,region} | {log_group,region} | {site} | {host,index}
  secret_ref  → secret_envelope          # 3P API keys (Datadog/Splunk) — encrypted, never in config plaintext
  status      draft | active | error | disabled
  cursor      CharField                  # replaces/augments IngestCheckpoint per source
  last_verified_at / last_error
```

Many rows per workspace = many simultaneous sources. This is the direct analog of
`WorkspacePaymentMethod`. The optional **catalog** of kinds (icon, `config_template` for the frontend
form) starts as a small **in-code registry** (not a DB table) to avoid over-building; promote to a
model only if the UI needs admin-editable catalog entries.

### D4 — `LogSourceProvider` registry (application/providers/log_source_provider.py)

`kind → LogSourcePort`, exactly like `PaymentGatewayProvider`. The composition root that knows the
concrete adapters exist; resolves `secret_ref` before handing `config` to an adapter. Nascent
adapters are **feature-flag gated** (like `payments.braintree` / `feature.container_security`) so they
ship dark until ready.

### D5 — S3 is the first adapter; CloudWatch proves the seam

- **`S3LogSourceAdapter`** — the existing assume-role → `list_objects_v2` → `get_object` → gunzip →
  parse logic **moves out of `log_ingest_service` into this adapter** (behavior-identical; the service
  now drives it through the port). This is the DRY win: one S3 read path, reused by the error scan and
  the pattern analyzer.
- **`CloudWatchLogSourceAdapter`** — `FilterLogEvents` over a log group (pull, `nextToken` cursor) —
  the **second real adapter that proves the port generalizes** (as Trivy proved `ScannerPort`).
- **`Datadog` / `Splunk`** adapters follow (Datadog Logs API by `site`; Splunk REST search by
  `host`/`index`), each behind the flag.

### D6 — Pull now, push later (same normalization)

v1 is **pull**: the ingest service periodically calls `read_window(config, since=cursor)` per enabled
source (Celery, `.iter…` windows). **Push** (a customer forwards to an autosec HTTP receiver, or a
Lambda streams from their S3) is a later **additive** driving adapter — a receiver endpoint that
writes the *same* normalized `LogRecord`s — not a rework. This matches the industry pull/push split.

### D7 — Deprecate `trail_s3_bucket`; the config becomes a first-class resource (root-fix)

`AwsOrganizationConnection.trail_s3_bucket` / `trail_s3_prefix` are **deprecated**. A data migration
seeds a `WorkspaceLogSource(kind="s3", config={bucket, prefix, role, region})` from any non-blank
existing value (so the demo keeps working with zero manual steps), and the S3 adapter reads from the
`WorkspaceLogSource`. **This is why the original regression cannot recur**: log configuration is no
longer a mutable field on an unrelated connection that a reconnect blanks — it is an owned resource
with its own create/verify/enable/disable lifecycle and its own audit trail.

### D8 — Secrets

Datadog/Splunk API keys and any bearer tokens are stored via the existing integrations
`secret_envelope` (encrypted at rest), referenced by `secret_ref`, resolved only inside the provider,
and **never** placed in `config` plaintext, logs, or error strings (`LogSourceHealth.detail` is
scrubbed). Consistent with the logging rule (never log secrets) and the AWS confused-deputy posture.

## Consequences

- Adding the Nth log source = a `LogSourcePort` adapter + a registry line + a `config_template` entry.
  Auth, paging, and format are the adapter's problem; checkpointing, dedupe, normalization, detection,
  and aggregation are inherited from the pipeline — solved once (mirrors "adding the Nth scanner").
- A workspace runs any mix of sources simultaneously; the HUD/map merge and tag by `source_kind`. The
  per-region map LOGS drill (FE #107) naturally extends: a region surfaces whichever configured
  source(s) cover it, honestly ("no source" when none) — true multi-region data residency.
- The original wipe regression is structurally impossible after D7.
- Cost: a new model + migration + a refactor of `log_ingest_service` behind the port. Mitigated by the
  strangler phases below (S3 stays working throughout).
- `IngestCheckpoint` is subsumed by the per-source `cursor` (migrate or bridge; not deleted in slice 1).

## Non-goals

- Not building a general log *analytics* store or replacing the customer's SIEM — autosec reads a
  recent window for SOC context + detection, not full retention.
- Not implementing all adapters at once — Datadog/Splunk land incrementally behind the flag.
- Not adding a graph/queue substrate — the existing Celery + Postgres pipeline is reused.

## Implementation plan (strangler — each step ships on its own; this ADR is the spec)

1. **Port + S3 adapter + registry.** Add `LogSourcePort` (D1), extend `LogRecord` (D2), extract
   `S3LogSourceAdapter` from `log_ingest_service` (D5), add `LogSourceProvider` (D4). Refactor the
   error scan + pattern analyzer to drive S3 through the port — behavior-identical, covered by the
   existing tests. *No new model yet; the adapter still reads `trail_s3_bucket` to stay green.*
2. **`WorkspaceLogSource` model** (D3) + data migration seeding an S3 row from `trail_s3_bucket` (D7);
   the S3 adapter reads the model; deprecate the connection fields. Unit + integration tests
   (idempotent seed, multi-source read, cursor advance).
3. **CRUD API** — add/verify/enable/disable a `WorkspaceLogSource` (mirrors the payments "add a
   method" flow); `verify` calls `LogSourcePort.verify`. Controller stays thin.
4. **`CloudWatchLogSourceAdapter`** (D5) behind a feature flag — the seam proof.
5. **Datadog + Splunk adapters** (D5, D8), each flag-gated, `secret_envelope` for keys.
6. **Frontend** — a "Log Sources" settings section (catalog → pick kind → `config_template` form →
   verify), and the per-region map LOGS drill reads the multi-source union tagged by `source_kind`.
7. **Push receiver** (D6) — an authenticated ingest endpoint writing normalized `LogRecord`s — once a
   customer needs forward-based delivery.
