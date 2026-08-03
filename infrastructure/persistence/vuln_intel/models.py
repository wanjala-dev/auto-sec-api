"""Threat-intel feed snapshots — immutable, dated, version-stamped (ADR 0013 D2).

EPSS (FIRST.org, exploitation *probability*) and CISA KEV (*confirmed* exploited) are
third-party reference feeds a security tool ingests. Per ``pin-versions.md`` they are
pulled once on a schedule into a **dated, version-stamped snapshot** and scored against
the stored snapshot — never live-fetched per request/scan — so contextual-risk scoring
is reproducible and a feed outage can't stall triage.

These tables hold *reference/enrichment data, not findings*: they do NOT create a
per-pillar finding table (ADR 0004 C6). The one Finding SSOT is enriched by CVE id via
the read-only ``VulnIntelPort``; nothing here references a Finding.

A snapshot is immutable: a same-day re-pull is idempotent on the feed's own version
(EPSS ``score_date`` / KEV ``catalogVersion``), never an in-place overwrite of the
scores/entries — the ``refresh_feeds`` job replaces a version's child rows atomically
so a partially-written pull can't be scored against.
"""

from __future__ import annotations

import uuid

from django.db import models


class EpssSnapshot(models.Model):
    """One daily EPSS pull, stamped with the feed's own ``score_date`` + ``model_version``.

    The child ``EpssScore`` rows carry the per-CVE probability/percentile. The read port
    resolves the latest snapshot (by ``score_date``) and looks CVEs up within it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Feed-native version stamps (pin-versions.md: a snapshot records what it is).
    score_date = models.DateField(help_text="EPSS feed's own score_date — the dated snapshot key.")
    model_version = models.CharField(
        max_length=32, blank=True, default="", help_text="EPSS model version, e.g. v2025.03.14."
    )

    fetched_at = models.DateTimeField(help_text="When this pull was ingested (wall clock).")
    record_count = models.PositiveIntegerField(default=0)
    checksum = models.CharField(
        max_length=64, blank=True, default="", help_text="Optional content checksum of the pull."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["score_date"], name="uniq_epss_snapshot_date"),
        ]
        indexes = [
            models.Index(fields=["-score_date"], name="epss_snapshot_latest_idx"),
        ]

    def __str__(self) -> str:
        return f"EPSS {self.score_date} ({self.record_count} CVEs)"


class EpssScore(models.Model):
    """A single CVE's EPSS probability + percentile within one snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(EpssSnapshot, on_delete=models.CASCADE, related_name="scores")

    cve = models.CharField(max_length=32, help_text="CVE id, e.g. CVE-2024-3094.")
    epss = models.FloatField(help_text="Probability [0-1] of exploitation in the next 30 days.")
    percentile = models.FloatField(help_text="Percentile rank [0-1] among all scored CVEs.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "cve"], name="uniq_epss_score_identity"),
        ]
        indexes = [
            # The scorer's lookup key: (snapshot, cve). Covers both single + batch reads.
            models.Index(fields=["snapshot", "cve"], name="epss_score_snap_cve_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.cve} epss={self.epss}"


class KevSnapshot(models.Model):
    """One CISA KEV catalog pull, stamped with the catalog's own ``catalogVersion``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    catalog_version = models.CharField(
        max_length=32, help_text="CISA KEV catalogVersion, e.g. 2026.08.01 — the snapshot key."
    )
    fetched_at = models.DateTimeField()
    record_count = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["catalog_version"], name="uniq_kev_snapshot_version"),
        ]
        indexes = [
            models.Index(fields=["-fetched_at"], name="kev_snapshot_latest_idx"),
        ]

    def __str__(self) -> str:
        return f"KEV {self.catalog_version} ({self.record_count} CVEs)"


class KevEntry(models.Model):
    """A single CVE with evidence of active exploitation, within one KEV snapshot."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(KevSnapshot, on_delete=models.CASCADE, related_name="entries")

    cve = models.CharField(max_length=32)
    date_added = models.DateField(null=True, blank=True, help_text="When CISA added the CVE to the catalog.")
    known_ransomware = models.BooleanField(default=False, help_text="knownRansomwareCampaignUse == 'Known'.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "cve"], name="uniq_kev_entry_identity"),
        ]
        indexes = [
            models.Index(fields=["snapshot", "cve"], name="kev_entry_snap_cve_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.cve} (KEV)"
