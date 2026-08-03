"""Django adapter implementing VulnSnapshotStorePort — writes the dated feed snapshots.

The single write path for threat-intel snapshots. A snapshot is immutable per version:
a same-version re-pull replaces that version's child rows inside one transaction, so a
half-written pull is never scored against. Child rows are ``bulk_create``d in batches
(EPSS is ~hundreds of thousands of CVEs).
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from components.vuln_intel.application.ports.vuln_snapshot_store_port import VulnSnapshotStorePort
from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, KevFeedSnapshot

_BULK_BATCH = 5000


def _stream_bulk_create(model, instances: Iterable) -> int:
    """``bulk_create`` an iterable of model instances in bounded batches of ``_BULK_BATCH``,
    holding at most one batch in memory at a time — flat memory regardless of feed size.

    Django's ``bulk_create`` eagerly ``list()``s whatever iterable it's handed to compute the
    length and split batches, so passing a 280k-row generator straight in still materializes
    the entire feed (~280k model instances) and OOM-kills the 768Mi worker. The caller MUST
    hand us the generator; we pull it one row at a time, flushing every ``_BULK_BATCH``. Returns
    the number of rows created."""
    total = 0
    batch: list = []
    for obj in instances:
        batch.append(obj)
        if len(batch) >= _BULK_BATCH:
            model.objects.bulk_create(batch, batch_size=_BULK_BATCH)
            total += len(batch)
            batch = []  # release the flushed batch before building the next
    if batch:
        model.objects.bulk_create(batch, batch_size=_BULK_BATCH)
        total += len(batch)
    return total


class VulnSnapshotRepository(VulnSnapshotStorePort):
    def save_epss_snapshot(self, snapshot: EpssFeedSnapshot) -> int:
        from django.utils import timezone

        from infrastructure.persistence.vuln_intel.models import EpssScore, EpssSnapshot

        with transaction.atomic():
            snap, _ = EpssSnapshot.objects.update_or_create(
                score_date=snapshot.score_date,
                defaults={
                    "model_version": snapshot.model_version,
                    "fetched_at": timezone.now(),
                    # Streaming means the true count is known only after the last batch drains;
                    # stamp 0 now and update below (see the trailing .update()).
                    "record_count": 0,
                    "checksum": snapshot.checksum,
                },
            )
            # Replace this date's scores atomically — a re-pull is idempotent, never partial.
            EpssScore.objects.filter(snapshot=snap).delete()
            # Stream the records (a lazy generator on the real feed — ~280k CVEs) into bounded
            # bulk_create batches. Django's bulk_create eagerly ``list()``s whatever it's given,
            # so feeding it the 280k-row generator directly would still materialize the lot and
            # OOM the 768Mi worker; we chunk here so at most _BULK_BATCH model instances ever
            # coexist in memory.
            count = _stream_bulk_create(
                EpssScore,
                (EpssScore(snapshot=snap, cve=r.cve, epss=r.epss, percentile=r.percentile) for r in snapshot.records),
            )
            EpssSnapshot.objects.filter(pk=snap.pk).update(record_count=count)
        return count

    def save_kev_snapshot(self, snapshot: KevFeedSnapshot) -> int:
        from django.utils import timezone

        from infrastructure.persistence.vuln_intel.models import KevEntry, KevSnapshot

        with transaction.atomic():
            snap, _ = KevSnapshot.objects.update_or_create(
                catalog_version=snapshot.catalog_version,
                defaults={
                    "fetched_at": timezone.now(),
                    "record_count": snapshot.record_count,
                    "checksum": snapshot.checksum,
                },
            )
            KevEntry.objects.filter(snapshot=snap).delete()
            KevEntry.objects.bulk_create(
                (
                    KevEntry(
                        snapshot=snap,
                        cve=r.cve,
                        date_added=r.date_added,
                        known_ransomware=r.known_ransomware,
                    )
                    for r in snapshot.records
                ),
                batch_size=_BULK_BATCH,
            )
        return snapshot.record_count

    def prune_snapshots(self, *, keep: int = 7) -> int:
        from infrastructure.persistence.vuln_intel.models import EpssSnapshot, KevSnapshot

        deleted = 0
        keep_epss = list(EpssSnapshot.objects.order_by("-score_date").values_list("id", flat=True)[:keep])
        _, per_model = EpssSnapshot.objects.exclude(id__in=keep_epss).delete()
        deleted += per_model.get("vuln_intel.EpssSnapshot", 0)
        keep_kev = list(KevSnapshot.objects.order_by("-fetched_at").values_list("id", flat=True)[:keep])
        _, per_model = KevSnapshot.objects.exclude(id__in=keep_kev).delete()
        deleted += per_model.get("vuln_intel.KevSnapshot", 0)
        return deleted

    def latest_epss_score_date(self) -> str | None:
        from infrastructure.persistence.vuln_intel.models import EpssSnapshot

        row = EpssSnapshot.objects.order_by("-score_date").values_list("score_date", flat=True).first()
        return row.isoformat() if row else None

    def latest_kev_catalog_version(self) -> str | None:
        from infrastructure.persistence.vuln_intel.models import KevSnapshot

        return KevSnapshot.objects.order_by("-fetched_at").values_list("catalog_version", flat=True).first()
