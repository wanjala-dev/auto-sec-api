"""Cloud asset graph — the resource nodes + typed edges (ADR 0004 / CLOUD_ASSET_GRAPH_SPIKE §4).

The code-to-cloud graph the attack-path correlation runs over. Workspace-scoped.
Substrate-agnostic by design (spike §3): the Prowler-derived inventory adapter fills
these rows now, and a CloudQuery adapter can backfill a complete inventory later with
no schema change.

Boundaries:
- ``asset_urn`` is the canonical cross-pillar correlation key (== a Finding's
  ``asset_urn``), carried BY VALUE so a finding and its graph node correlate without a
  cross-context FK (ADR 0004 D4).
- ``aws_account_link_id`` is a SOFT reference into the ``integrations`` context (a plain
  UUID, not a hard FK) — cloud_graph persistence stays decoupled from integrations
  persistence; the application layer resolves the link via a port (spike §8).
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class CloudAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="cloud_assets")
    # Soft reference into the integrations context (no hard cross-context FK).
    aws_account_link_id = models.UUIDField(null=True, blank=True)

    # Identity / correlation
    provider = models.CharField(max_length=16, default="aws")
    arn = models.CharField(max_length=512, help_text="ARN / globally-unique resource id — the dedup key.")
    asset_urn = models.CharField(max_length=512, help_text="AssetUrn.value — cross-pillar correlation key.")

    # Data
    resource_type = models.CharField(max_length=64, help_text="e.g. aws_ec2_instance, aws_iam_role, aws_s3_bucket.")
    region = models.CharField(max_length=32, blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")
    exposure = models.CharField(max_length=16, default="private", help_text="public | internal | private (derived).")
    attributes = models.JSONField(default=dict, help_text="Normalized resource config (JSON-safe).")

    # Lifecycle timestamps, set explicitly by the sync (not auto_now) so a re-sync never
    # rewrites first_seen.
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    is_deleted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "arn"], name="uniq_cloud_asset_identity"),
        ]
        indexes = [
            models.Index(fields=["workspace", "resource_type"], name="casset_ws_type_idx"),
            models.Index(fields=["workspace", "asset_urn"], name="casset_ws_urn_idx"),
            models.Index(fields=["workspace", "exposure"], name="casset_ws_exposure_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.resource_type}:{self.arn}"


class CloudAssetEdge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="cloud_asset_edges")
    src_asset = models.ForeignKey(CloudAsset, on_delete=models.CASCADE, related_name="edges_out")
    dst_asset = models.ForeignKey(CloudAsset, on_delete=models.CASCADE, related_name="edges_in")

    relation = models.CharField(
        max_length=32,
        help_text="Typed relationship, e.g. can_assume, attached_to, allows_ingress_from, has_policy.",
    )
    attributes = models.JSONField(default=dict)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["src_asset", "dst_asset", "relation"], name="uniq_cloud_asset_edge"),
        ]
        indexes = [
            models.Index(fields=["workspace", "relation"], name="cedge_ws_relation_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.src_asset_id} -{self.relation}-> {self.dst_asset_id}"


class AttackPath(models.Model):
    """Materialised, ranked toxic-combination path (ADR 0004 §6 / ADR 0005 §6).

    A precomputed read table: the attack-path correlation job (a background detector
    cycle) fully recomputes a workspace's paths and replaces the rows; the HUD read is a
    single indexed ``SELECT ... ORDER BY risk_score DESC``. Denormalised on purpose (a
    materialised view, not a normalised store) — entry/target ids + labels + the leg
    chain are inlined so the read needs no joins. ``id`` is a deterministic uuid5 of
    (workspace, entry, target, category) so a re-materialisation is idempotent.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="attack_paths")

    # Ranking
    category = models.CharField(max_length=32, help_text="AttackPathCategory.value — the toxic-combo kind.")
    severity = models.CharField(max_length=16, help_text="Severity.value")
    risk_band = models.CharField(max_length=8, help_text="RiskBand.value — green | amber | red.")
    risk_score = models.FloatField(help_text="0–100 contextual risk.")

    # Endpoints (denormalised — soft asset ids, within-context)
    entry_asset_id = models.UUIDField()
    entry_asset_urn = models.CharField(max_length=512)
    entry_label = models.CharField(max_length=255)
    target_asset_id = models.UUIDField()
    target_asset_urn = models.CharField(max_length=512)
    target_label = models.CharField(max_length=255)

    # Presentation + evidence
    title = models.CharField(max_length=512)
    explanation = models.TextField(blank=True, default="")
    length = models.PositiveIntegerField(default=0, help_text="Hop count (edges) entry → target.")
    legs = models.JSONField(default=list, help_text="Ordered hops: [{src_id, src_label, relation, dst_id, dst_label}].")
    asset_urns = models.JSONField(default=list, help_text="Ordered node chain (entry → … → target).")

    computed_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "-risk_score"], name="apath_ws_risk_idx"),
            models.Index(fields=["workspace", "category"], name="apath_ws_category_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.category}:{self.entry_label}→{self.target_label} ({self.risk_score})"
