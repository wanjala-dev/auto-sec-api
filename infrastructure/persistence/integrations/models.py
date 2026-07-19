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
* **SinkConnector** — outbound alert sinks (Slack first). Secrets are stored
  via the app-layer encryption envelope, never plaintext.

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
    # Ingestion wiring (org trail → central S3 → SQS)
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


class SinkConnector(models.Model):
    class Kind(models.TextChoices):
        SLACK = "slack", "Slack"
        WEBHOOK = "webhook", "Generic webhook"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="sink_connectors")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120)
    # Non-secret config (channel name, min severity, url host…).
    config = models.JSONField(default=dict, blank=True)
    # Encrypted secret material (bot token / signing secret) — Fernet envelope
    # applied at the application layer; NEVER plaintext.
    secret_ciphertext = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "kind", "is_enabled"])]
