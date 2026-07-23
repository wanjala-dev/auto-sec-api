"""Provenance & access graph persistence — who (human / service account / AI
agent / vendor integration) can touch what, and what they actually touched.

This is the Postgres-first graph substrate for the ``components/provenance``
bounded context (``docs/plans/PROVENANCE_ACCESS_GRAPH_2026-07-17.md``). It is a
unified, workspace-scoped, append-only graph over four node/edge types:

* **ProvenanceActor** (node) — a human, service account, AI agent, or vendor
  integration. The human maps to a ``CustomUser``; the AI agent to an ``Agent``
  id; the vendor to an integration connection.
* **ProvenanceResource** (node) — a thing acted upon (system, data store, repo,
  channel, bucket, record).
* **AccessGrant** (permission edge) — ``Actor → Resource`` with a permission set
  and the source system that granted it. This is the *potential* ("what can
  they reach").
* **ProvenanceEvent** (action edge) — ``Actor → Resource`` "did X at time T".
  This is the *actual* ("what did they do"). Internal events are projected from
  ``EntityAuditLog`` + ``ai`` actions + identity sessions; external ones are
  ingested from vendor audit logs in later slices.

Design notes
------------
* **Postgres-first (deliberate).** Adjacency tables + recursive CTE for the
  hall-tree traversal. A dedicated graph store is added ONLY if traversal depth
  demands it (see the plan's open question and the CNAPP lens in
  ``SECURITY_POSTURE_VISION_2026-07-20.md`` §10 — Neo4j/Cartography rejected).
* **Append-only.** Nodes/events are immutable once written. A grant's observed
  lifecycle is recorded on the grant itself (``last_seen_at`` / ``revoked_at``);
  history is never rewritten.
* **Workspace-scoped.** Row-level tenancy, same as the rest of the platform.
  Every query scopes to a single workspace.
* **The gap between potential and actual is the signal.** A grant with zero
  events in N days is an unused permission → a least-privilege finding on the
  triage board (Slice 3).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ActorType(models.TextChoices):
    HUMAN = "human", "Human"
    SERVICE_ACCOUNT = "service_account", "Service account"
    AI_AGENT = "ai_agent", "AI agent"
    VENDOR_INTEGRATION = "vendor_integration", "Vendor / integration"


class PermissionLevel(models.TextChoices):
    READ = "read", "Read"
    WRITE = "write", "Write"
    EXECUTE = "execute", "Execute"
    ADMIN = "admin", "Admin"


class SourceSystem(models.TextChoices):
    """Where a node/edge was observed. Extended as connectors land."""

    INTERNAL = "internal", "autosec internal (audit trail)"
    AI = "ai", "autosec AI agents"
    IDENTITY = "identity", "autosec identity (sessions / roles)"
    AWS = "aws", "AWS (IAM / CloudTrail)"
    OKTA = "okta", "Okta"
    GOOGLE_WORKSPACE = "google_workspace", "Google Workspace"
    SLACK = "slack", "Slack"
    GITHUB = "github", "GitHub"


class ProvenanceActor(models.Model):
    """A node that can hold grants and perform actions.

    Identity resolution across systems (same human = Okta = Google = GitHub) is
    a later-slice concern; for Slice 0 each ``(source_system, external_ref)`` is
    its own actor and ``user`` links the internal ones back to a ``CustomUser``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="provenance_actors")

    actor_type = models.CharField(max_length=24, choices=ActorType.choices)
    source_system = models.CharField(max_length=24, choices=SourceSystem.choices)
    # Stable identifier of this actor within its source system (a user id, an
    # IAM role ARN, an agent id, an integration id).
    external_ref = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default="")

    # Soft links back to internal principals (nullable — an external vendor
    # actor has none). Kept as loose references to avoid hard cross-context
    # coupling on the AI/integration side.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="provenance_actors",
    )
    agent_ref = models.UUIDField(null=True, blank=True, help_text="Agent.agent_id for ai_agent actors.")
    integration_ref = models.CharField(max_length=64, blank=True, default="")

    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_system", "external_ref"],
                name="uniq_provenance_actor_identity",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "actor_type"], name="prov_actor_ws_type_idx"),
            models.Index(fields=["workspace", "source_system"], name="prov_actor_ws_src_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.actor_type}:{self.display_name or self.external_ref}"


class ProvenanceResource(models.Model):
    """A node acted upon — a system, data store, repo, channel, bucket, record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="provenance_resources")

    resource_type = models.CharField(max_length=64)
    source_system = models.CharField(max_length=24, choices=SourceSystem.choices)
    external_ref = models.CharField(max_length=512)
    display_name = models.CharField(max_length=255, blank=True, default="")

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_system", "external_ref"],
                name="uniq_provenance_resource_identity",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "resource_type"], name="prov_res_ws_type_idx"),
            models.Index(fields=["workspace", "source_system"], name="prov_res_ws_src_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.resource_type}:{self.display_name or self.external_ref}"


class AccessGrant(models.Model):
    """Permission edge (``Actor → Resource``) — the *potential*.

    ``permissions`` is a list of :class:`PermissionLevel` values. ``source``
    records which system conferred the grant (an IAM policy, an OAuth scope, an
    Okta role, an internal ``WorkspaceMembership.role``).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="provenance_grants")
    actor = models.ForeignKey(ProvenanceActor, on_delete=models.CASCADE, related_name="grants")
    resource = models.ForeignKey(ProvenanceResource, on_delete=models.CASCADE, related_name="grants")

    permissions = models.JSONField(default=list, help_text="List of PermissionLevel values.")
    scope = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(max_length=255, blank=True, default="", help_text="What conferred the grant.")

    granted_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    # Observed revocation. Null = still in effect. History is never rewritten;
    # a re-grant after revocation is a new row.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "actor", "resource", "scope"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_active_grant_per_actor_resource_scope",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "actor"], name="prov_grant_ws_actor_idx"),
            models.Index(fields=["workspace", "resource"], name="prov_grant_ws_res_idx"),
            models.Index(fields=["workspace", "revoked_at"], name="prov_grant_ws_revoked_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.actor_id} →[{','.join(self.permissions or [])}] {self.resource_id}"


class ProvenanceEvent(models.Model):
    """Action edge (``Actor → Resource``) — the *actual*. Append-only.

    ``origin`` + ``origin_id`` link the event back to the store it was projected
    from (an ``EntityAuditLog`` row, an AI action, an identity session) so the
    graph never duplicates the source of truth — it indexes it.
    """

    class Origin(models.TextChoices):
        AUDIT_LOG = "audit_log", "EntityAuditLog"
        AI_ACTION = "ai_action", "AI action"
        IDENTITY_SESSION = "identity_session", "Identity session"
        VENDOR_LOG = "vendor_log", "Vendor audit log"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="provenance_events")
    actor = models.ForeignKey(ProvenanceActor, on_delete=models.CASCADE, related_name="events")
    resource = models.ForeignKey(ProvenanceResource, on_delete=models.CASCADE, related_name="events")

    action = models.CharField(max_length=128)
    occurred_at = models.DateTimeField()
    source_system = models.CharField(max_length=24, choices=SourceSystem.choices)

    # Provenance metadata: ip, session id, request id, tool, etc.
    metadata = models.JSONField(default=dict, blank=True)

    # Idempotent projection key back to the originating store.
    origin = models.CharField(max_length=24, choices=Origin.choices)
    origin_id = models.CharField(max_length=64)

    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "origin", "origin_id"],
                name="uniq_provenance_event_projection",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "actor", "occurred_at"], name="prov_evt_ws_actor_ts_idx"),
            models.Index(fields=["workspace", "resource", "occurred_at"], name="prov_evt_ws_res_ts_idx"),
            models.Index(fields=["workspace", "occurred_at"], name="prov_evt_ws_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.actor_id} {self.action} {self.resource_id} @ {self.occurred_at:%Y-%m-%d}"
