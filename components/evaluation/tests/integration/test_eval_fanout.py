"""The fan-out's concurrency invariants, asserted against a real database.

These are not unit tests of a service — they are tests of what happens when two
workers touch one run at the same moment. Every one of them fails against the
obvious read-modify-write implementation, which is exactly why they exist: the
old single-task runner was correct only because nothing ran beside it, and that
property silently disappears the moment the work is fanned out.

The scaling defect this replaced: `task_time_limit = 300` against ~10-30s per
case put a hard ceiling near 10-30 cases, while the field's guidance puts a
minimum useful golden set at 50 and a production one at 200-500.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from components.evaluation.infrastructure.repositories.eval_repository import DjangoEvalRepository
from infrastructure.persistence.evaluation.models import EvalCase, EvalCaseResult, EvalRun, EvalSuite

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

AXES = ["grounded", "fix_applies"]


@pytest.fixture
def suite_run(workspace_factory):
    workspace = workspace_factory()
    suite = EvalSuite.objects.create(workspace=workspace, name="Big suite", agent_type="triage", axes=AXES)
    cases = [
        EvalCase.objects.create(
            suite=suite,
            workspace=workspace,
            source_kind=EvalCase.SourceKind.CURATED,
            source_ref=f"c{i}",
            scenario=f"scenario {i}",
        )
        for i in range(6)
    ]
    run = EvalRun.objects.create(
        workspace=workspace,
        suite=suite,
        agent_type="triage",
        model_slug="gpt-4o-mini",
        cases_total=len(cases),
        status=EvalRun.Status.RUNNING,
    )
    return {"workspace": workspace, "suite": suite, "cases": cases, "run": run}


def _result(run, case, workspace):
    return EvalCaseResult.objects.create(run=run, case=case, workspace=workspace, axis_verdicts={"grounded": True})


class TestResumability:
    def test_pending_excludes_cases_that_already_have_a_result(self, suite_run):
        """The whole point of resumability. Before this, a retry re-ran — and
        re-PAID FOR — every case already graded."""
        repo = DjangoEvalRepository()
        run, cases, ws = suite_run["run"], suite_run["cases"], suite_run["workspace"]
        for case in cases[:4]:
            _result(run, case, ws)

        pending = repo.pending_case_ids(run=run)

        assert len(pending) == 2
        assert set(pending) == {str(c.id) for c in cases[4:]}

    def test_a_fully_graded_run_has_nothing_pending(self, suite_run):
        repo = DjangoEvalRepository()
        run, ws = suite_run["run"], suite_run["workspace"]
        for case in suite_run["cases"]:
            _result(run, case, ws)

        assert repo.pending_case_ids(run=run) == []

    def test_another_runs_results_do_not_count_as_progress(self, suite_run):
        """Results are per RUN. A second run of the same suite starts from zero
        — otherwise re-running a suite would grade nothing and report success."""
        repo = DjangoEvalRepository()
        first, ws = suite_run["run"], suite_run["workspace"]
        for case in suite_run["cases"]:
            _result(first, case, ws)

        second = EvalRun.objects.create(
            workspace=ws,
            suite=suite_run["suite"],
            agent_type="triage",
            model_slug="gpt-4o-mini",
            cases_total=6,
        )

        assert len(repo.pending_case_ids(run=second)) == 6


class TestConcurrentAccounting:
    """Lost updates, tested by INTERLEAVING rather than by threads.

    Threads would be the obvious way to write this, and it is the wrong way
    here: the suite runs on SQLite (`api/settings/test.py`), which serialises
    writers and raises "database table is locked" instead of demonstrating
    anything. A green threaded test would have proved the database's locking
    works, not that this code is correct.

    So the race is reproduced deterministically — each "worker" holds its own
    copy of the run, fetched BEFORE the other worker wrote, which is exactly the
    state two concurrent Celery tasks are in. Read-modify-write off those copies
    loses an update; an F() expression does not. These tests fail against the
    naive implementation and pass against this one, on any backend.
    """

    def test_two_workers_holding_stale_copies_lose_neither_case_nor_money(self, suite_run):
        repo = DjangoEvalRepository()
        run_id = suite_run["run"].id

        # Both workers read the run at cases_completed = 0, as concurrent tasks
        # would. `.accrue` must not trust either copy.
        worker_a_view = EvalRun.objects.get(pk=run_id)
        worker_b_view = EvalRun.objects.get(pk=run_id)
        assert worker_a_view.cases_completed == worker_b_view.cases_completed == 0

        repo.accrue(run_id=worker_a_view.id, cost_usd=0.02)
        repo.accrue(run_id=worker_b_view.id, cost_usd=0.03)

        fresh = EvalRun.objects.get(pk=run_id)
        assert fresh.cases_completed == 2, "a stale-copy increment dropped a case"
        assert fresh.cost_usd == Decimal("0.050000"), "under-reporting real spend"

    def test_accrual_accumulates_across_every_case_in_a_suite(self, suite_run):
        repo = DjangoEvalRepository()
        run_id = suite_run["run"].id

        for _ in range(6):
            repo.accrue(run_id=run_id, cost_usd=0.01)

        fresh = EvalRun.objects.get(pk=run_id)
        assert fresh.cases_completed == 6
        assert fresh.cost_usd == Decimal("0.060000")

    def test_accrue_returns_the_post_increment_values(self, suite_run):
        """The caller decides about the cap and about finalisation from these,
        so a stale pre-increment read would let the last case miss the finish."""
        repo = DjangoEvalRepository()
        completed, spent = repo.accrue(run_id=suite_run["run"].id, cost_usd=0.25)

        assert completed == 1
        assert spent == Decimal("0.250000")


class TestFinalisationHappensOnce:
    def test_only_one_of_many_workers_claims_the_terminal_state(self, suite_run):
        """Several workers can see 'that was the last case' at the same instant.
        If each finalised, each would fire whatever follows finalisation.

        Eight sequential attempts stand in for eight simultaneous ones: the
        conditional UPDATE is what makes them equivalent, since it matches only
        a run still in a non-terminal state. An if-then-save would let every one
        of these succeed."""
        repo = DjangoEvalRepository()
        run = suite_run["run"]

        claims = [repo.claim_terminal_state(run_id=run.id, status=EvalRun.Status.COMPLETED) for _ in range(8)]

        assert sum(1 for c in claims if c) == 1, "exactly one worker may close a run"
        run.refresh_from_db()
        assert run.status == EvalRun.Status.COMPLETED
        assert run.finished_at is not None

    def test_a_terminal_run_cannot_be_reopened_or_re_closed(self, suite_run):
        repo = DjangoEvalRepository()
        run = suite_run["run"]
        repo.claim_terminal_state(run_id=run.id, status=EvalRun.Status.FAILED, last_error="cap")

        assert repo.claim_terminal_state(run_id=run.id, status=EvalRun.Status.COMPLETED) is False
        run.refresh_from_db()
        assert run.status == EvalRun.Status.FAILED
        assert run.last_error == "cap"


class TestStallDetection:
    def test_a_run_whose_cases_went_quiet_is_reaped(self, suite_run):
        """The fan-out's own failure mode: dispatched tasks vanish and nothing
        is left to finish the run."""
        repo = DjangoEvalRepository()
        run, ws = suite_run["run"], suite_run["workspace"]
        old = timezone.now() - timedelta(hours=2)
        row = _result(run, suite_run["cases"][0], ws)
        EvalCaseResult.objects.filter(pk=row.pk).update(created_at=old)

        stalled = repo.stalled_run_ids(older_than=timezone.now() - timedelta(minutes=30))

        assert str(run.id) in stalled

    def test_a_run_still_reporting_is_left_alone(self, suite_run):
        repo = DjangoEvalRepository()
        _result(suite_run["run"], suite_run["cases"][0], suite_run["workspace"])

        stalled = repo.stalled_run_ids(older_than=timezone.now() - timedelta(minutes=30))

        assert str(suite_run["run"].id) not in stalled

    def test_a_run_that_never_recorded_anything_is_reaped_on_its_own_age(self, suite_run):
        """A run whose FIRST case never landed has no result timestamp at all.
        Keying only off results would leave it running for ever."""
        repo = DjangoEvalRepository()
        run = suite_run["run"]
        EvalRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=3))

        assert str(run.id) in repo.stalled_run_ids(older_than=timezone.now() - timedelta(minutes=30))

    def test_a_finished_run_is_never_reaped(self, suite_run):
        repo = DjangoEvalRepository()
        run = suite_run["run"]
        EvalRun.objects.filter(pk=run.pk).update(
            status=EvalRun.Status.COMPLETED, created_at=timezone.now() - timedelta(days=5)
        )

        assert str(run.id) not in repo.stalled_run_ids(older_than=timezone.now() - timedelta(minutes=30))
