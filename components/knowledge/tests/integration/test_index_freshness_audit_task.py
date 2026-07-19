"""Integration tests for the ``audit_index_freshness`` Celery task.

Pins three things the task contract promises:

* Walks every active workspace, persists one ``IndexFreshnessSample``
  per workspace per pass.
* Inactive workspaces are skipped.
* The summary dict reports compliance fraction + emits a WARNING
  log line when the per-pass SLO compliance drops below the floor.

The task uses the real ports + adapters in this test — no port
injection — because the surface the contract guarantees is
end-to-end. Use-case-level tests live in ``unit/`` and exercise the
math against fakes.
"""
from __future__ import annotations

import logging

import pytest

from components.knowledge.infrastructure.tasks.index_freshness_tasks import (
    PASS_COMPLIANCE_TARGET,
    audit_index_freshness,
)


@pytest.mark.django_db
class TestAuditIndexFreshnessTask:
    def test_writes_one_sample_per_active_workspace(
        self, workspace_factory
    ):
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )

        ws_a = workspace_factory()
        ws_b = workspace_factory()
        inactive = workspace_factory()
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        summary = audit_index_freshness.apply().result
        assert summary["total_workspaces"] == 2

        samples = list(
            IndexFreshnessSample.objects.values_list(
                "workspace_id", flat=True
            )
        )
        assert ws_a.id in samples
        assert ws_b.id in samples
        assert inactive.id not in samples

    def test_freshly_created_workspace_marked_fresh(
        self, workspace_factory
    ):
        """A workspace created moments before the audit is fresh.

        Under test settings the eager-Celery reindex fires
        synchronously from the workspace post_save signal, so by
        the time the audit runs the workspace IS indexed. Either
        way, lag rounds to 0 (sub-second) and the SLA is met. The
        test pins those two assertions only — the rest of the
        sample shape is exercised in unit tests against the
        use case."""
        from infrastructure.persistence.ai.aggregations.models import (
            IndexFreshnessSample,
        )

        ws = workspace_factory()
        audit_index_freshness.apply()

        sample = IndexFreshnessSample.objects.get(workspace=ws)
        assert sample.lag_seconds == 0
        assert sample.sla_met is True
        # The workspace row counts as an event (its updated_at is
        # "just now") regardless of whether the index ran.
        assert sample.latest_event_time is not None

    def test_summary_reports_compliance_fraction(self, workspace_factory):
        workspace_factory()
        workspace_factory()
        summary = audit_index_freshness.apply().result
        assert summary["sla_met"] == 2
        assert summary["total_workspaces"] == 2
        assert summary["compliance_fraction"] == 1.0
        assert summary["pass_target_met"] is True
        assert summary["pass_compliance_target"] == PASS_COMPLIANCE_TARGET

    def test_no_active_workspaces_returns_clean_summary(self):
        summary = audit_index_freshness.apply().result
        assert summary["total_workspaces"] == 0
        assert summary["sla_met"] == 0
        assert summary["compliance_fraction"] == 1.0
        assert summary["pass_target_met"] is True

    def test_warning_logged_when_compliance_below_target(
        self, workspace_factory, caplog, monkeypatch
    ):
        """If the SLO compliance drops below PASS_COMPLIANCE_TARGET,
        the task emits a WARNING line naming the compliance number
        so an operator tailing logs can spot the regression.

        Force the SLO miss by:
          1. Setting the per-row SLA target to 0 seconds, AND
          2. Forcing the workspace's ``updated_at`` back by 1 hour
             so the lag is ≥ 1 second and DOESN'T round to 0.

        Both are necessary — sub-second sample-to-event drift still
        rounds to zero seconds, which passes a 0-second SLA.
        """
        from datetime import timedelta

        from django.utils import timezone

        from components.knowledge.infrastructure.tasks import (
            index_freshness_tasks,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        monkeypatch.setattr(
            "components.knowledge.application.use_cases."
            "measure_index_freshness_use_case.DEFAULT_SLA_TARGET_SECONDS",
            0,
        )

        ws = workspace_factory()
        past = timezone.now() - timedelta(hours=1)
        Workspace.objects.filter(pk=ws.pk).update(updated_at=past)
        # Eager-Celery wrote a chunk during workspace creation;
        # delete it so the SLO miss isn't masked by an "index is
        # newer than event" verdict.
        from infrastructure.persistence.ai.models import EmbeddingChunk

        EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(ws.id)
        ).delete()

        with caplog.at_level(
            logging.WARNING,
            logger="components.knowledge.infrastructure.tasks.index_freshness_tasks",
        ):
            summary = index_freshness_tasks.audit_index_freshness.apply().result

        assert summary["pass_target_met"] is False
        warns = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "index freshness SLO violated" in r.getMessage()
        ]
        assert warns, (
            "Expected a WARNING log when SLO compliance drops below the "
            "PASS_COMPLIANCE_TARGET floor."
        )
