"""Integrations persistence — org-scale AWS onboarding + connector registry.

Design (validated against how Wiz/Panther/Datadog-class vendors onboard):

* **AwsOrganizationConnection** — ONE row per customer AWS Organization per
  workspace. We generate the ``external_id`` (vendor-generated, never
  customer-chosen — confused-deputy defense) and hand the customer a
  CloudFormation template that creates the read role in the management
  account and (optionally) a **StackSet with service-managed permissions +
  auto-deployment** so every current AND future member account gets the same
  role automatically — no tickets, no drift.
* **AwsAccountLink** — one row per member account discovered via
  ``organizations:ListAccounts`` through the management role. Each is
  independently verified by ``sts:AssumeRole`` and carries its own status, so
  one broken account never blocks the rest of the org.
* **IngestCheckpoint** — per (connection, account, region, channel) ingestion
  cursor. SQS-first (queue URL + stateless consumers, horizontally scalable,
  DLQ for poison messages); S3 prefix-listing checkpoint as the fallback
  channel. Event-level idempotency lives in the findings pipeline (dedupe on
  CloudTrail ``eventID`` — duplicates are documented AWS behaviour).
* **DeliveryConnection** — outbound delivery channels (Slack first; Teams /
  Discord / generic webhook / SMTP follow as adapters land, ADR 0016). One row
  per destination, carrying its own event subscriptions and severity floor.
  Secrets are stored via the app-layer encryption envelope, never plaintext —
  note an incoming-webhook URL *is* a bearer credential and lives there too.

Everything is workspace-scoped (row-level tenancy, same as the rest of the
platform).
"""

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class AwsOrganizationConnection(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending — template not yet deployed"
        VERIFYING = "verifying", "Verifying role assumption"
        CONNECTED = "connected", "Connected"
        DEGRADED = "degraded", "Degraded — some accounts failing"
        ERROR = "error", "Error"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="aws_connections")
    name = models.CharField(max_length=120, default="AWS Organization")
    # Customer side
    management_account_id = models.CharField(max_length=12)
    organization_id = models.CharField(max_length=34, blank=True, default="")
    role_name = models.CharField(max_length=128, default="AutoSecAuditRole")
    # Vendor-generated confused-deputy token — unique per connection.
    external_id = models.CharField(max_length=64, unique=True)
    regions = models.JSONField(default=list, help_text="Regions to ingest from; empty = all enabled.")
    # Org-wide rollout: StackSet w/ service-managed perms + auto-deployment.
    org_wide = models.BooleanField(default=True)
    # Ingestion wiring (org trail → central S3 → SQS).
    # DEPRECATED (ADR 0008 D7): the S3 log location now lives on a first-class
    # WorkspaceLogSource(kind=s3) row (seeded from these by migration 0006), so a
    # re-verify can't blank where logs are read from. The read path prefers the
    # WorkspaceLogSource and only falls back to these transitionally. Do not add
    # new readers of these fields; a later migration drops the columns.
    trail_s3_bucket = models.CharField(max_length=255, blank=True, default="")
    trail_s3_prefix = models.CharField(max_length=255, blank=True, default="")
    sqs_queue_url = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "management_account_id"],
                name="uniq_ws_aws_mgmt_account",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.management_account_id})"


class AwsAccountLink(models.Model):
    class Status(models.TextChoices):
        DISCOVERED = "discovered", "Discovered"
        VERIFIED = "verified", "Role verified"
        FAILED = "failed", "Assume-role failing"
        SUSPENDED = "suspended", "Suspended in org"
        EXCLUDED = "excluded", "Excluded by operator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(AwsOrganizationConnection, on_delete=models.CASCADE, related_name="accounts")
    account_id = models.CharField(max_length=12)
    account_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DISCOVERED)
    last_assumed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["connection", "status"])]
        constraints = [models.UniqueConstraint(fields=["connection", "account_id"], name="uniq_conn_account")]


class IngestCheckpoint(models.Model):
    class Channel(models.TextChoices):
        SQS = "sqs", "SQS notifications (primary)"
        S3_LIST = "s3_list", "S3 prefix listing (fallback)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(AwsOrganizationConnection, on_delete=models.CASCADE, related_name="checkpoints")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.SQS)
    # S3_LIST cursor: last fully-processed object key; SQS is stateless.
    last_object_key = models.CharField(max_length=1024, blank=True, default="")
    last_event_time = models.DateTimeField(null=True, blank=True)
    objects_processed = models.BigIntegerField(default=0)
    events_processed = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "account_id", "region", "channel"],
                name="uniq_ingest_cursor",
            )
        ]


class WorkspaceLogSource(models.Model):
    """A configured log source for a workspace (ADR 0008).

    Many rows per workspace = many sources ingested at once (an S3 trail, a
    CloudWatch log group, a Datadog site, a Splunk index, an HTTP webhook). The
    per-kind ``config`` is opaque to the core — each ``LogSourcePort`` adapter
    knows its own shape. Crucially this is a FIRST-CLASS, owned resource with its
    own lifecycle, so log configuration survives operations on other resources: an
    AWS connection re-verify can no longer silently blank *where* logs are read
    from (the regression that motivated ADR 0008). The S3 location lives here; the
    connection only vends the assume-role credentials.
    """

    class Kind(models.TextChoices):
        S3 = "s3", "Amazon S3 trail"
        CLOUDWATCH = "cloudwatch", "Amazon CloudWatch Logs"
        DATADOG = "datadog", "Datadog"
        SPLUNK = "splunk", "Splunk"
        WEBHOOK = "webhook", "HTTP webhook (push)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ERROR = "error", "Error"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="log_sources")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120, default="")
    # Per-kind, opaque to the core. S3: {aws_connection_id, bucket, prefix}.
    # CloudWatch: {aws_connection_id, log_group, region}. Datadog: {site}. Splunk:
    # {host, index}. 3P API keys are NEVER stored here in plaintext — they ride on
    # ``secret_ref`` (a secret_envelope id) once those adapters land.
    config = models.JSONField(default=dict, blank=True)
    secret_ref = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    # Per-source ingestion cursor (generalizes IngestCheckpoint.last_object_key
    # across source kinds — an S3 key, a CloudWatch nextToken, a time cursor).
    cursor = models.CharField(max_length=1024, blank=True, default="")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["workspace", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.name or self.id}"


class LogPatternRollup(models.Model):
    """Temporal aggregate of a recurring log pattern — the memory that lets the
    optimization advisor reason about logs *over time* rather than one window.

    Each aggregation run normalizes every log line to a stable ``signature``
    (task name / health-check shape, with volatile IDs stripped), then upserts
    the running rollup for that ``(connection, signature)``. ``runs_observed``
    and ``last_window_count`` are what make an optimization signal trustworthy:
    a pattern flagged only when it is BOTH high-frequency AND sustained across
    several runs — never a one-window blip. Deterministic; no LLM writes here.
    """

    class Kind(models.TextChoices):
        PERIODIC_TASK = "periodic_task", "Scheduled/periodic task"
        HEALTH_CHECK = "health_check", "Health-check / housekeeping noise"
        VOLUME = "volume", "High-volume service chatter"
        OTHER = "other", "Other recurring pattern"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(
        AwsOrganizationConnection, on_delete=models.CASCADE, related_name="log_pattern_rollups"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="log_pattern_rollups")
    service = models.CharField(max_length=120, default="")
    signature = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER)
    sample_message = models.CharField(max_length=500, blank=True, default="")
    # Cumulative + per-run counters (the "over time" signal).
    total_count = models.BigIntegerField(default=0)
    last_window_count = models.IntegerField(default=0)
    peak_window_count = models.IntegerField(default=0)
    runs_observed = models.IntegerField(default=0)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    # When we last raised an optimization finding for this pattern — throttles
    # re-flagging so a persistent noisy task doesn't file a card every run.
    last_flagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["connection", "signature"], name="uniq_conn_log_signature"),
        ]
        indexes = [models.Index(fields=["workspace", "kind"])]

    def __str__(self):
        return f"{self.kind}:{self.signature} ×{self.total_count}"


class LogMetricBucket(models.Model):
    """Hourly security-metric bucket — the deterministic fact store behind
    "chat with the logs" (log_analytics_agent) and the posture dashboards.

    Every ingested log window is classified by pure regex (see
    ``components.integrations.application.log_metrics_service``) into the
    metric taxonomy below and folded into hourly buckets keyed by
    ``(connection, metric, service, source, bucket_start)``. Counting and
    trend questions ("how many SSH attempts this week?", "did we get
    DDoSed?") are answered by ORM aggregates over these rows — NEVER by RAG
    and NEVER by an LLM. **No LLM ever writes to this table** (the
    aggregation-first rule from the posture vision doc §3.2/§4).

    This is deliberately a SEPARATE table from ``LogPatternRollup`` — that
    model is the optimization advisor's cumulative per-signature memory;
    this one is a time-series of security metrics. Overloading the rollup
    would conflate two different question shapes (tuning advice vs.
    quantitative analytics).
    """

    class Metric(models.TextChoices):
        AUTH_FAILURE = "auth_failure", "Authentication failure (failed logins / SSH attempts / invalid user)"
        HTTP_5XX = "http_5xx", "HTTP 5xx server error responses"
        HTTP_4XX = "http_4xx", "HTTP 4xx client error responses"
        SQLI_SIGNATURE = "sqli_signature", "SQL-injection-shaped payload (UNION SELECT, ' OR 1=1, …)"
        SCANNER = "scanner", "Scanner user agents / probing paths (sqlmap, nikto, /wp-admin, /.env)"
        APP_ERROR = "app_error", "ERROR-level application log lines"
        APP_WARNING = "app_warning", "WARNING-level application log lines"
        TOTAL_VOLUME = "total_volume", "All log lines (lines/day + DDoS volume baseline)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="log_metric_buckets")
    connection = models.ForeignKey(
        AwsOrganizationConnection, on_delete=models.CASCADE, related_name="log_metric_buckets"
    )
    metric = models.CharField(max_length=32, choices=Metric.choices)
    service = models.CharField(max_length=120, default="")
    # Source IP/host when derivable from the line (attack-shaped metrics);
    # "" when not derivable or not meaningful (app_*/total_volume).
    source = models.CharField(max_length=64, default="")
    # Hour-truncated UTC timestamp of the bucket.
    bucket_start = models.DateTimeField()
    count = models.IntegerField(default=0)
    sample_message = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "metric", "service", "source", "bucket_start"],
                name="uniq_log_metric_bucket",
            )
        ]
        indexes = [models.Index(fields=["workspace", "metric", "bucket_start"])]

    def __str__(self):
        return f"{self.metric}@{self.bucket_start:%Y-%m-%d %H}h {self.service} x{self.count}"


class GitHubConnection(models.Model):
    """Workspace-scoped GitHub access for agent draft-PR remediation.

    **DEPRECATED (ADR 0010):** superseded by :class:`VcsConnection` (provider-tagged,
    multi-provider). Kept transitionally as the data-migration source; the read path
    now uses ``VcsConnection``. Dropped in a later phase once no code reads it.

    Phase A (dogfood): a fine-grained PAT, stored via the app-layer Fernet
    envelope (``components.integrations.application.providers.
    secret_envelope_provider``) — NEVER plaintext. ``repo_allowlist`` is the
    consent boundary: the agent may only open draft PRs against repos the
    operator explicitly listed. Phase B replaces the PAT with a GitHub App
    installation (short-lived, per-operation tokens).
    """

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="github_connections")
    name = models.CharField(max_length=120, default="GitHub")
    # "owner/repo" strings the agent may open draft PRs against — the consent
    # boundary. A repo not on this list is rejected before any API call.
    repo_allowlist = models.JSONField(default=list, blank=True)
    # Encrypted fine-grained PAT — Fernet envelope applied at the application
    # layer (same envelope as DeliveryConnection secrets); NEVER plaintext.
    token_ciphertext = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "status"])]

    def __str__(self):
        return f"{self.name} ({self.workspace_id})"


class VcsConnection(models.Model):
    """Workspace-scoped VCS access for agent draft-PR remediation (ADR 0010).

    Generalizes :class:`GitHubConnection` across code hosts. **Many rows per
    workspace** — an org can link GitHub *and* GitLab *and* Bitbucket at once, each
    with its own ``repo_allowlist`` + secret. ``repo_allowlist`` is the consent
    boundary: the agent may only open draft PRs against repos the operator listed.
    The encrypted token is a fine-grained PAT (Phase A) via the app-layer Fernet
    envelope (``secret_envelope_provider``) — NEVER plaintext. Phase B replaces it
    with a provider App installation (short-lived, per-operation tokens).
    """

    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        GITLAB = "gitlab", "GitLab"
        BITBUCKET = "bitbucket", "Bitbucket"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    class CommitIdentity(models.TextChoices):
        # Who the draft-PR commit is attributed to on the code host.
        PAT_OWNER = "pat_owner", "PAT owner (default — no author/committer sent)"
        OPERATOR = "operator", "The approving operator (their name + email)"
        CUSTOM = "custom", "A fixed custom name + email"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="vcs_connections")
    provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.GITHUB)
    name = models.CharField(max_length=120, default="GitHub")
    # "owner/repo" (or project path) strings the agent may open draft PRs against —
    # the consent boundary. A repo not on this list is rejected before any API call.
    repo_allowlist = models.JSONField(default=list, blank=True)
    # Optional self-hosted host (GitLab CE/EE, Bitbucket Server); blank = the SaaS host.
    base_url = models.CharField(max_length=255, blank=True, default="")
    # Optional monorepo subdirectory the app lives under (e.g. "api-v2.0"). When set,
    # a finding's runtime-relative path is prefixed with this (deterministic, no tree
    # fetch) instead of auto-detecting. Blank = auto-detect from the repo tree. Applies
    # to all of this connection's allowlisted repos.
    repo_root = models.CharField(max_length=200, blank=True, default="")
    # Who the draft-PR commit is attributed to. Default ``pat_owner`` preserves the
    # historical behavior (no author/committer sent → GitHub attributes it to the PAT
    # owner). ``operator`` stamps the approving human; ``custom`` uses the pinned
    # name/email below. The name/email columns apply ONLY when ``custom``.
    commit_identity = models.CharField(max_length=16, choices=CommitIdentity.choices, default=CommitIdentity.PAT_OWNER)
    commit_author_name = models.CharField(max_length=120, blank=True, default="")
    commit_author_email = models.EmailField(blank=True, default="")
    # Encrypted fine-grained PAT — Fernet envelope at the application layer (same
    # envelope as DeliveryConnection/GitHubConnection secrets); NEVER plaintext.
    token_ciphertext = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "provider", "status"])]

    def __str__(self):
        return f"{self.name} [{self.provider}] ({self.workspace_id})"


class VercelConnection(models.Model):
    """Workspace-scoped Vercel access for posture scanning (ADR 0021 D2).

    Token-shaped like :class:`VcsConnection` (the GitHub-PAT precedent), NOT the AWS
    role-assumption outlier: an encrypted Vercel API token via the ONE integrations
    Fernet envelope (``secret_envelope_provider``) — NEVER plaintext. The documented
    ask is a token minted from a **Viewer-role seat**, scoped to ONE team, **with an
    expiration** (least-privilege by the role system, since Vercel tokens have no
    read-only variant).

    ``credential_kind`` is the day-one discriminator so the OAuth connectable
    integration (ADR 0021 P4) lands later as an additive kind on the same row —
    the log-source ``Kind`` precedent. The named team is the CONSENT boundary:
    scans are always pinned to it (``VERCEL_TEAM``); an unpinned token would make
    Prowler scan every team the token's user belongs to (ADR 0021 D3).
    """

    class CredentialKind(models.TextChoices):
        TOKEN = "token", "API token"
        OAUTH_INTEGRATION = "oauth_integration", "OAuth connectable integration (P4 — not yet available)"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="vercel_connections")
    name = models.CharField(max_length=120, default="Vercel")
    # The ONE team this connection consents to scan. The operator supplies an id
    # (``team_…``) or a slug; verify() resolves + records the canonical trio.
    team_id = models.CharField(max_length=64, blank=True, default="")
    team_slug = models.CharField(max_length=64, blank=True, default="")
    team_name = models.CharField(max_length=255, blank=True, default="")
    credential_kind = models.CharField(max_length=24, choices=CredentialKind.choices, default=CredentialKind.TOKEN)
    # Encrypted API token — Fernet envelope at the application layer (same envelope
    # as VcsConnection/DeliveryConnection secrets); NEVER plaintext.
    token_ciphertext = models.TextField(blank=True, default="")
    # Recorded by verify() when the Vercel API exposes it — the expiry-nag surface
    # (D2: we ask for an expiring token, so we must warn before it lapses).
    token_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "status"])]

    def __str__(self):
        return f"{self.name} ({self.team_slug or self.team_id or 'no team'}) [{self.workspace_id}]"

    @property
    def team_ref(self) -> str:
        """The scan/verify target: the canonical id when known, else the slug."""
        return self.team_id or self.team_slug


def default_delivery_events() -> list[str]:
    """Event keys a new connection subscribes to (ADR 0016 D4 — sane defaults, all on).

    Mirrors the notifications ``EXTERNAL_EVENT_CATALOG``. Kept as a literal here so
    persistence stays free of bounded-context imports; a fitness test in the
    notifications context asserts the two never drift.
    """
    return ["draft_pr_opened", "finding_critical", "scan_failed", "scan_digest"]


class DeliveryConnection(models.Model):
    """One outbound destination a workspace has connected (ADR 0016).

    Workspace-level by nature — a team channel, not a personal inbox — which is why
    the notifications funnel delivers to it once per event rather than once per
    recipient.
    """

    class Kind(models.TextChoices):
        SLACK = "slack", "Slack"
        WEBHOOK = "webhook", "Generic webhook"

    class AuthMode(models.TextChoices):
        WEBHOOK_URL = "webhook_url", "Incoming webhook URL"
        BOT_TOKEN = "bot_token", "Bot token"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="delivery_connections")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120)
    auth_mode = models.CharField(max_length=16, choices=AuthMode.choices, default=AuthMode.WEBHOOK_URL)
    # Non-secret config (channel label, display hints).
    config = models.JSONField(default=dict, blank=True)
    # Subscribed event keys; empty list means "deliver nothing" (explicit, not a
    # fallback to defaults — an operator who unticks everything meant it).
    events = models.JSONField(default=default_delivery_events, blank=True)
    # The noise dial. Promoted out of ``config`` so it is queryable and typed;
    # mirrors components.integrations.domain.alert_policy.DEFAULT_MIN_SEVERITY.
    min_severity = models.CharField(max_length=16, default="high")
    # Encrypted credential — bot token OR incoming-webhook URL. Fernet envelope
    # applied at the application layer; NEVER plaintext.
    secret_ciphertext = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "kind", "is_enabled"]),
            models.Index(fields=["workspace", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name or self.kind} [{self.kind}] ({self.workspace_id})"
