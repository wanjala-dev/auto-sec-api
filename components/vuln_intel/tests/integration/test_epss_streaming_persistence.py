"""EPSS persistence is streamed + batched — it must never materialize the whole ~280k feed.

Regression guard for the OOM that killed the 768Mi celery worker on the real EPSS CSV: the
adapter used to build one tuple of ~280k ``EpssRecord`` and the store handed the whole
generator to ``bulk_create`` (which ``list()``s it internally), so ~280k model instances +
the record tuple coexisted in RAM. The fix streams the parse and chunks the insert so at most
``_BULK_BATCH`` rows ever live at once. These tests prove ``bulk_create`` is called in bounded
chunks (never once with the whole feed) and that the record source is consumed lazily.
"""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest

from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, EpssRecord
from components.vuln_intel.infrastructure.repositories import vuln_snapshot_repository as repo_mod
from components.vuln_intel.infrastructure.repositories.vuln_snapshot_repository import VulnSnapshotRepository

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_BATCH = repo_mod._BULK_BATCH  # 5000


def _record_stream(n: int, *, seen: list[int] | None = None):
    """A lazy generator of ``n`` synthetic EpssRecords. If ``seen`` is given, appends the
    running count as each record is produced — lets a test assert the source is pulled
    incrementally (streamed), not drained up front."""
    for i in range(n):
        if seen is not None:
            seen.append(i)
        yield EpssRecord(cve=f"CVE-2026-{i:06d}", epss=0.5, percentile=0.5)


class TestEpssStreamedPersistence:
    def test_bulk_create_is_called_in_bounded_chunks_not_once(self):
        # 2.5 batches worth of rows: expect 3 bulk_create calls of 5000 / 5000 / 2500.
        total = _BATCH * 2 + 2500
        snapshot = EpssFeedSnapshot(
            score_date=date(2026, 8, 3),
            model_version="v1",
            records=_record_stream(total),
        )

        from infrastructure.persistence.vuln_intel.models import EpssScore

        real_bulk_create = EpssScore.objects.bulk_create
        chunk_sizes: list[int] = []

        def _spy(objs, *args, **kwargs):
            objs = list(objs)
            chunk_sizes.append(len(objs))
            return real_bulk_create(objs, *args, **kwargs)

        with mock.patch.object(EpssScore.objects, "bulk_create", side_effect=_spy):
            written = VulnSnapshotRepository().save_epss_snapshot(snapshot)

        assert written == total
        # Chunked, NOT one giant call: 3 calls, none exceeding the batch ceiling.
        assert len(chunk_sizes) == 3, chunk_sizes
        assert chunk_sizes == [_BATCH, _BATCH, 2500]
        assert max(chunk_sizes) <= _BATCH
        # Never a single call carrying the whole feed.
        assert total not in chunk_sizes

    def test_record_source_is_consumed_lazily(self):
        # The store must pull the record generator incrementally. If it drained the whole
        # generator before the first bulk_create, `seen` would already hold every index when
        # the first chunk is flushed. We assert only one batch has been pulled at first flush.
        total = _BATCH * 2
        seen: list[int] = []
        pulled_at_first_flush: list[int] = []

        from infrastructure.persistence.vuln_intel.models import EpssScore

        real_bulk_create = EpssScore.objects.bulk_create

        def _spy(objs, *args, **kwargs):
            objs = list(objs)
            if not pulled_at_first_flush:
                pulled_at_first_flush.append(len(seen))
            return real_bulk_create(objs, *args, **kwargs)

        snapshot = EpssFeedSnapshot(
            score_date=date(2026, 8, 4),
            model_version="v1",
            records=_record_stream(total, seen=seen),
        )
        with mock.patch.object(EpssScore.objects, "bulk_create", side_effect=_spy):
            VulnSnapshotRepository().save_epss_snapshot(snapshot)

        # At the first flush only ~one batch of records had been produced, not the whole feed.
        assert pulled_at_first_flush[0] <= _BATCH + 1
        assert len(seen) == total  # all eventually consumed

    def test_stamps_streamed_record_count_on_snapshot_row(self):
        total = _BATCH + 17
        snapshot = EpssFeedSnapshot(
            score_date=date(2026, 8, 5),
            model_version="v1",
            records=_record_stream(total),
        )
        written = VulnSnapshotRepository().save_epss_snapshot(snapshot)

        from infrastructure.persistence.vuln_intel.models import EpssScore, EpssSnapshot

        row = EpssSnapshot.objects.get(score_date=date(2026, 8, 5))
        assert written == total
        assert row.record_count == total  # count known only after the stream drained
        assert EpssScore.objects.filter(snapshot=row).count() == total
