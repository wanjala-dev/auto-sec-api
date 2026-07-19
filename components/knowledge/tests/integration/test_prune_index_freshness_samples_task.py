"""Integration tests for the ``prune_index_freshness_samples`` task.

Two contract bits to pin:

* Rows older than the retention window get deleted.
* Recent rows survive — the prune doesn't wipe the working set.

The prune uses plain ``.filter(sample_time__lt=cutoff).delete()`` —
no clever batching. At our scale that's fine; the integration test
is the trip-wire that catches a future refactor changing the
semantics.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from components.knowledge.infrastructure.tasks.index_freshness_tasks import (
    INDEX_FRESHNESS_SAMPLE_RETENTION_DAYS,
    prune_index_freshness_samples,
)


@pytest.mark.django_db
class TestPruneIndexFreshnessSamples:
    def _make_sample(self, *, workspace, sample_time):
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )

        return IndexFreshnessSample.objects.create(
            workspace=workspace,
            sample_time=sample_time,
            latest_event_time=None,
            latest_index_time=None,
            lag_seconds=0,
            sla_target_seconds=600,
            sla_met=True,
        )

    def test_deletes_rows_older_than_retention(self, workspace_factory):
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )

        ws = workspace_factory()
        now = timezone.now()

        old_sample = self._make_sample(
            workspace=ws,
            sample_time=now
            - timedelta(days=INDEX_FRESHNESS_SAMPLE_RETENTION_DAYS + 1),
        )
        recent_sample = self._make_sample(
            workspace=ws,
            sample_time=now - timedelta(days=1),
        )

        result = prune_index_freshness_samples.apply().result
        assert result["rows_deleted"] >= 1

        assert not IndexFreshnessSample.objects.filter(
            pk=old_sample.pk
        ).exists()
        assert IndexFreshnessSample.objects.filter(
            pk=recent_sample.pk
        ).exists()

    def test_no_rows_to_prune_returns_zero(self, workspace_factory):
        ws = workspace_factory()
        self._make_sample(
            workspace=ws,
            sample_time=timezone.now() - timedelta(hours=1),
        )

        result = prune_index_freshness_samples.apply().result
        assert result["rows_deleted"] == 0

    def test_explicit_retention_days_override(self, workspace_factory):
        """The task accepts a ``retention_days`` arg so a one-off
        aggressive prune is possible without redeploying with a new
        default."""
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )

        ws = workspace_factory()
        old_sample = self._make_sample(
            workspace=ws,
            sample_time=timezone.now() - timedelta(hours=2),
        )

        # 1-hour retention forces the 2h-old row to drop.
        result = prune_index_freshness_samples.apply(
            kwargs={"retention_days": 0}
        ).result
        assert result["retention_days"] == 0
        assert not IndexFreshnessSample.objects.filter(
            pk=old_sample.pk
        ).exists()
