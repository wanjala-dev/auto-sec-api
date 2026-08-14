"""Finding — the normalized security-finding SSOT (ADR 0004 D1).

Every scanning pillar (Prowler today; Trivy/Checkov later) projects into this one
table via ``FindingObserved`` → the ``findings`` context, so severity/status/identity
are comparable across pillars and dedup + lifecycle live in one place. The board
``Task`` becomes a *local copy* of a Finding (a later phase), not the finding itself.

Identity is ``(workspace, source, fingerprint)`` — a nightly re-scan of the same
misconfiguration updates ``last_seen_at`` on the existing row instead of creating a
duplicate. ``asset_urn`` is the cross-pillar correlation key (carried by value, no FK
to the graph — ADR 0004 D4).
"""

from __future__ import annotations

import uuid

from django.db import models

from components.shared_platform.infrastructure.tenancy.managers import WorkspaceScopedManager

from infrastructure.persistence.workspaces.models import Workspace


class Finding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="findings")

    # Identity — the dedup key. ``source`` is the pillar/scanner ("cloud_posture.prowler").
    source = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=255)
    # Cross-pillar correlation key (AssetUrn.value). Indexed for the graph join.
    asset_urn = models.CharField(max_length=512)

    # Normalized (OCSF-aligned) severity/status — the shared value objects' .value.
    severity = models.CharField(max_length=16)
    status = models.CharField(max_length=16, default="open")

    title = models.CharField(max_length=512)
    description = models.TextField(blank=True, default="")
    remediation = models.TextField(blank=True, default="")
    compliance = models.JSONField(default=dict, help_text="Framework tags, e.g. {'CIS-2.0': ['2.1.5']}.")
    attributes = models.JSONField(default=dict, help_text="Pillar-specific extras.")

    # Run provenance (audit R2): the ScanRun of the LAST observation — soft
    # reference (no cross-context FK, matching connection/account refs elsewhere),
    # "" for run-less sources (detector cycles, log ingest). Finding → run →
    # trigger/triggered_by/engine_version becomes a plain lookup.
    scan_run_id = models.CharField(max_length=64, blank=True, default="")

    # Risk-acceptance context on the suppress lifecycle action (ADR 0015 D9):
    # the operator's "why" + optional time-box. ``resolve``/``reopen`` clear both.
    # Enforcement of the expiry (auto-reopen beat task) is P2 — the columns ship
    # now so the data is captured from day one.
    status_reason = models.TextField(blank=True, default="")
    suppress_expires_at = models.DateTimeField(null=True, blank=True)

    # Lifecycle timestamps, set explicitly by the use case (not auto_now) so a
    # status change never spuriously rewrites the observation window.
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    # ── Tenancy (ADR 0029) — HALF-FLIPPED, deliberately ─────────────────
    #
    # ``unscoped`` exists and the cross-workspace call sites already say so, but
    # ``objects`` is still a plain manager. Swapping this one line to
    # ``WorkspaceScopedManager()`` turns on fail-closed workspace scoping for
    # findings — and measured on 2026-08-14 that breaks 69 tests across 23 files
    # which query ``Finding.objects`` without binding a workspace. Every one is
    # a test that has to say which workspace it means; none is a product bug.
    #
    # Landing the flip and its ~43 test conversions in the same change as the
    # router would have made a green run impossible to attribute. So the
    # boundary is drawn here: the router is live, the vocabulary exists, and the
    # per-model flip is its own reviewable change.
    objects = models.Manager()
    unscoped = models.Manager()

    class Meta:
        # Related-object traversal (finding.tag_links, workspace.findings) goes
        # through the BASE manager. Pointing it at ``unscoped`` keeps FK
        # descriptors working when no workspace is bound — a related lookup is
        # already reached via a row the caller legitimately holds, so scoping it
        # again would break traversal without adding isolation.
        base_manager_name = "unscoped"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source", "fingerprint"],
                name="uniq_finding_identity",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "severity", "-last_seen_at"], name="finding_ws_sev_seen_idx"),
            models.Index(fields=["workspace", "status", "-last_seen_at"], name="finding_ws_status_seen_idx"),
            models.Index(fields=["workspace", "asset_urn"], name="finding_ws_urn_idx"),
            # "Findings of run X" — the run-detail / provenance drill-down read.
            models.Index(fields=["workspace", "scan_run_id"], name="finding_ws_run_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"


class FindingTag(models.Model):
    """Tag assignment on a finding (ADR 0015 D10) — an edge, not a record.

    FKs the tagging context's vocabulary at the persistence ring (single-DB;
    cross-app ORM FKs are normal here — the component boundary governs
    ``components.*`` imports, not outermost-ring model relations).

    ``workspace`` is denormalized from ``finding`` for the scoped
    ``(workspace, tag)`` index — the use case sets it from the loaded finding,
    never from client input. The ``finding``/``workspace`` FKs are
    ``db_index=False`` because each is the leading column of one of the two
    Meta indexes (a separate single-column index would be duplicate write
    cost); the ``tag`` FK keeps Django's default FK index (the composite does
    not prefix-cover tag-only lookups, and the FK integrity path needs it).
    """

    SOURCE_CHOICES = (("user", "User"), ("agent", "Agent"), ("rule", "Rule"), ("system", "System"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="finding_tags", db_index=False)
    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="tag_links", db_index=False)
    tag = models.ForeignKey("tagging.Tag", on_delete=models.CASCADE, related_name="finding_links")
    applied_by = models.UUIDField(null=True, blank=True)  # actor user id; null = platform (mirrors actor_id)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="user")
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["finding", "tag"], name="uniq_finding_tag")]
        indexes = [models.Index(fields=["workspace", "tag"], name="findingtag_ws_tag_idx")]

    def __str__(self) -> str:
        return f"{self.finding_id} ← {self.tag_id}"


class WorkspaceAttckCoverage(models.Model):
    """Materialized MITRE ATT&CK coverage heatmap for a workspace (perf rule §6).

    A background task aggregates the workspace's open findings by ATT&CK technique
    into ``coverage`` (``{"tactics": [...], "totals": {...}}``); the HUD read is a
    single-row SELECT. One row per workspace, overwritten on each recompute.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="attck_coverage")
    coverage = models.JSONField(default=dict, help_text="The heatmap blob: tactics → techniques with counts.")
    technique_count = models.IntegerField(default=0)
    finding_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"ATT&CK coverage ({self.technique_count} techniques)"


class FindingRisk(models.Model):
    """Materialized per-finding contextual-risk score (ADR 0013 / ADR 0004 §6).

    A background job (``findings.recompute_finding_risk``) blends CVSS/severity × EPSS ×
    CISA KEV × graph-exposure into a 0–100 score and writes this denormalized read row;
    the findings list + Today brief read it with a single indexed ``ORDER BY score DESC``
    — the heavy blend never runs inline in a request (§6 HARD RULE). One row per finding
    (OneToOne), recomputed-not-incremented, so a rescore is idempotent.

    Correlation is by value-identity, not FK into other contexts (C4): the CVE id (from
    the finding's ``attributes``) resolves EPSS/KEV, and the ``AssetUrn`` resolves
    exposure — both read through ports. The ``epss_score_date`` / ``kev_catalog_version``
    / ``model_version`` stamps make each score reproducible + auditable (ADR 0013 D6).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # workspace denormalized for the (workspace, -score) ranked read + scoping.
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="finding_risks")
    finding = models.OneToOneField(Finding, on_delete=models.CASCADE, related_name="risk")

    # The materialized score + its explainable breakdown.
    score = models.FloatField(default=0.0, help_text="0–100 contextual risk (higher = more urgent).")
    band = models.CharField(max_length=8, help_text="RiskBand.value — green | amber | red.")
    factors = models.JSONField(default=list, help_text="RiskFactor breakdown [{key,label,points,detail}].")

    # Signal snapshot (denormalized for display + the 'risk that matters' filters).
    epss = models.FloatField(null=True, blank=True, help_text="EPSS probability [0-1], or null if no CVE match.")
    epss_percentile = models.FloatField(null=True, blank=True)
    in_kev = models.BooleanField(default=False, help_text="CVE is in the CISA KEV catalog (confirmed exploited).")
    exposure = models.CharField(max_length=16, default="private", help_text="Applied amplifier bucket.")
    exposure_unknown = models.BooleanField(
        default=False, help_text="No graph signal — damped to private but flagged (ADR 0013 decision #3)."
    )

    # Reproducibility / audit stamps.
    model_version = models.CharField(max_length=32, default="", help_text="Scorer blend version.")
    epss_score_date = models.CharField(
        max_length=16, blank=True, default="", help_text="EPSS snapshot date scored against."
    )
    kev_catalog_version = models.CharField(
        max_length=32, blank=True, default="", help_text="KEV catalog version scored against."
    )
    scored_at = models.DateTimeField()

    class Meta:
        indexes = [
            # The ranked read: filter(workspace).order_by("-score"). Mirrors AttackPath.
            models.Index(fields=["workspace", "-score"], name="finding_risk_ws_score_idx"),
            models.Index(fields=["workspace", "in_kev"], name="finding_risk_ws_kev_idx"),
        ]

    def __str__(self) -> str:
        return f"risk={self.score} band={self.band}"
