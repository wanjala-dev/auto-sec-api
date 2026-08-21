"""A run is pinned to the cases it started with.

Two separate guarantees, and it is worth being clear about which is which.

The SNAPSHOT protects a run in flight: it iterates the case list frozen at
creation, so editing the suite while a run is going cannot move that run's
denominator underneath it. The FINGERPRINT protects the score afterwards: it
records which questions were asked, so two scores are only ever compared when
they came from the same exam.

Mining never exposed either problem, because history only appends. Letting
people author and edit their own cases is what makes both acute.
"""

from __future__ import annotations

import pytest

from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
from infrastructure.persistence.evaluation.models import EvalCase, EvalCaseResult, EvalRun, EvalSuite

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

AXES = ["grounded"]


@pytest.fixture
def suite(workspace_factory):
    workspace = workspace_factory()
    suite = EvalSuite.objects.create(workspace=workspace, name="S", agent_type="triage", axes=AXES)
    for i in range(3):
        EvalCase.objects.create(
            suite=suite,
            workspace=workspace,
            source_kind=EvalCase.SourceKind.CURATED,
            source_ref=f"c{i}",
            scenario=f"scenario {i}",
            solution_criteria=["names the bucket"],
        )
    return suite


def _run(repo, suite):
    return repo.create_run(
        workspace_id=suite.workspace_id,
        suite=suite,
        agent_type="triage",
        model_slug="gpt-4o-mini",
    )


class TestTheSnapshotIsFrozen:
    def test_a_run_records_the_cases_it_started_with(self, suite):
        repo = DjangoEvalRepository()
        run = _run(repo, suite)

        assert len(run.case_snapshot) == 3
        assert run.cases_total == 3
        assert run.dataset_hash

    def test_a_case_added_mid_run_is_not_part_of_that_run(self, suite):
        """Otherwise a suite that grows while a run is going moves the run's own
        denominator: "34 of 40" silently becomes "34 of 47" with nothing new
        graded, and the run can never reach its total."""
        repo = DjangoEvalRepository()
        run = _run(repo, suite)

        EvalCase.objects.create(
            suite=suite,
            workspace_id=suite.workspace_id,
            source_kind=EvalCase.SourceKind.CURATED,
            source_ref="late",
            scenario="added after the run began",
        )

        pending = repo.pending_case_ids(run=run)
        assert len(pending) == 3
        assert set(pending) == set(run.case_snapshot)

    def test_the_snapshot_still_drives_resumability(self, suite):
        repo = DjangoEvalRepository()
        run = _run(repo, suite)
        first = EvalCase.objects.filter(suite=suite).first()
        EvalCaseResult.objects.create(run=run, case=first, workspace_id=suite.workspace_id, axis_verdicts={})

        pending = repo.pending_case_ids(run=run)

        assert len(pending) == 2
        assert str(first.id) not in pending

    def test_a_legacy_run_without_a_snapshot_falls_back_to_the_live_suite(self, suite):
        """Runs predating this change have an empty snapshot. They must keep
        working exactly as they did rather than reading as zero-case runs."""
        repo = DjangoEvalRepository()
        run = _run(repo, suite)
        EvalRun.objects.filter(pk=run.pk).update(case_snapshot=[])
        run.refresh_from_db()

        assert len(repo.pending_case_ids(run=run)) == 3


class TestDriftDetection:
    def test_editing_a_case_moves_the_suite_hash_away_from_the_run_that_scored_it(self, suite):
        """This is the comparison the panel refuses to draw."""
        repo = DjangoEvalRepository()
        run = _run(repo, suite)

        case = EvalCase.objects.filter(suite=suite).first()
        case.solution_criteria = ["something entirely different"]
        case.save(update_fields=["solution_criteria"])

        current = repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=str(suite.workspace_id))
        assert current != run.dataset_hash

    def test_an_untouched_suite_still_matches_its_run(self, suite):
        repo = DjangoEvalRepository()
        run = _run(repo, suite)

        current = repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=str(suite.workspace_id))
        assert current == run.dataset_hash

    def test_two_runs_of_an_unchanged_suite_share_a_version(self, suite):
        repo = DjangoEvalRepository()

        assert _run(repo, suite).dataset_hash == _run(repo, suite).dataset_hash


class TestTenantScoping:
    def test_the_hash_covers_only_this_workspaces_cases(self, suite, workspace_factory):
        """Every read here is workspace-scoped; on the pooled tier that filter
        IS the tenant boundary."""
        repo = DjangoEvalRepository()
        other = workspace_factory()

        assert repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=str(other.id)) != repo.suite_dataset_hash(
            suite_id=str(suite.id), workspace_id=str(suite.workspace_id)
        )
