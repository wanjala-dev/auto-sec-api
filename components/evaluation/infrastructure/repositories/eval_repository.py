"""ORM access for evaluation (ADR 0033).

Every query here filters on ``workspace_id``. On the pooled tier that filter is
the tenant boundary — there is no database boundary behind it — so a method
that forgets it does not return slightly wrong data, it returns another
customer's quality evidence.
"""

from __future__ import annotations

from decimal import Decimal

from components.evaluation.application.ports.eval_ports import CaseSourcePort, EvalCaseInput
from components.evaluation.domain.value_objects.claim_tier import AxisEvidence
from components.evaluation.domain.value_objects.dataset_version import (
    CaseFingerprintInput,
    fingerprint,
)


class DjangoEvalRepository(CaseSourcePort):
    # ── cases ───────────────────────────────────────────────────────────────

    def load_cases(self, *, suite_id: str, workspace_id: str) -> list[EvalCaseInput]:
        from infrastructure.persistence.evaluation.models import EvalCase

        rows = EvalCase.objects.filter(suite_id=suite_id, workspace_id=workspace_id).order_by("created_at")
        return [_to_case_input(row) for row in rows]

    def pending_case_ids(self, *, run) -> list[str]:
        """Case IDs in this run's suite that have NO result yet.

        This is what makes a run resumable, and it is the difference between a
        retry costing nothing and a retry costing the whole suite again. The
        previous shape re-read every case unconditionally, so an interrupted
        300-case run restarted at case 1 and paid a second time for the 200 it
        had already graded.

        Correctness rests on the ``(run, case)`` unique constraint on
        ``EvalCaseResult``: a result row is the durable record that a case is
        done, so "done" survives a worker dying mid-suite.

        Pending is computed against the run's OWN frozen ``case_snapshot``, not
        against a fresh query of the suite. That distinction is what stops a
        suite edited mid-flight from changing a run underneath itself: cases
        added after the run started are not part of it, and a case deleted from
        the suite does not silently shrink the denominator a rate is computed
        over.

        Runs created before snapshots existed have an empty one; those fall back
        to the live suite, which is the behaviour they already had.
        """
        from infrastructure.persistence.evaluation.models import EvalCase, EvalCaseResult

        done = {
            str(pk)
            for pk in EvalCaseResult.objects.filter(run=run, workspace_id=run.workspace_id).values_list(
                "case_id", flat=True
            )
        }

        snapshot = [str(cid) for cid in (run.case_snapshot or [])]
        if snapshot:
            return [cid for cid in snapshot if cid not in done]

        rows = (
            EvalCase.objects.filter(suite_id=run.suite_id, workspace_id=run.workspace_id)
            .order_by("created_at")
            .values_list("id", flat=True)
        )
        return [str(pk) for pk in rows if str(pk) not in done]

    def get_case_input(self, *, case_id: str, workspace_id: str) -> EvalCaseInput | None:
        from infrastructure.persistence.evaluation.models import EvalCase

        row = EvalCase.objects.filter(id=case_id, workspace_id=workspace_id).first()
        return _to_case_input(row) if row else None

    # ── suites ──────────────────────────────────────────────────────────────

    def list_suites(self, *, workspace_id: str):
        from django.db.models import Count

        from infrastructure.persistence.evaluation.models import EvalSuite

        return (
            EvalSuite.objects.filter(workspace_id=workspace_id)
            .annotate(case_count=Count("cases"))
            .order_by("-created_at")
        )

    def get_suite(self, *, suite_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalSuite

        return EvalSuite.objects.filter(id=suite_id, workspace_id=workspace_id).first()

    def latest_run_for(self, *, suite_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(suite_id=suite_id, workspace_id=workspace_id).order_by("-created_at").first()

    # ── runs ────────────────────────────────────────────────────────────────

    def create_run(self, *, workspace_id, suite, agent_type, model_slug, cases_total=None):
        """Open a run and FREEZE the dataset it will be scored against.

        `cases_total` is derived here rather than taken from the caller, because
        it has to agree with the snapshot exactly. A caller-supplied total that
        drifted from the frozen case list would leave a run that can never
        finish (total too high) or that finalises early with cases ungraded
        (total too low).
        """
        from infrastructure.persistence.evaluation.models import EvalCase, EvalRun

        rows = list(
            EvalCase.objects.filter(suite_id=suite.id, workspace_id=workspace_id)
            .order_by("created_at")
            .values("id", "scenario", "prompt_inputs", "solution_criteria")
        )
        snapshot = [str(row["id"]) for row in rows]

        return EvalRun.objects.create(
            workspace_id=workspace_id,
            suite=suite,
            agent_type=agent_type,
            model_slug=model_slug,
            cases_total=len(snapshot) if cases_total is None else cases_total,
            status=EvalRun.Status.PENDING,
            case_snapshot=snapshot,
            # The system prompt is part of the question in prompt mode, so it
            # participates in the fingerprint — otherwise editing the prompt and
            # re-running reads as the model changing.
            dataset_hash=_fingerprint_rows(rows, system_prompt=suite.system_prompt),
        )

    def create_authored_suite(
        self,
        *,
        workspace_id,
        name,
        agent_type,
        axes,
        mode,
        system_prompt,
        forked_from_prompt_id,
        cases,
    ):
        """Persist an authored suite and its cases in ONE transaction.

        Atomic on purpose: a suite row that survives while its cases fail leaves
        an empty suite the operator did not ask for, and the panel would offer
        to run it.
        """
        from django.db import transaction

        from infrastructure.persistence.evaluation.models import EvalCase, EvalSuite

        with transaction.atomic():
            suite = EvalSuite.objects.create(
                workspace_id=workspace_id,
                name=name,
                agent_type=agent_type,
                axes=list(axes),
                origin=EvalSuite.Origin.AUTHORED,
                mode=mode,
                system_prompt=system_prompt or "",
                forked_from_prompt_id=forked_from_prompt_id or "",
            )
            EvalCase.objects.bulk_create(
                [
                    EvalCase(
                        suite=suite,
                        workspace_id=workspace_id,
                        source_kind=EvalCase.SourceKind.AUTHORED,
                        # Falls back to the row's position so the
                        # (suite, source_kind, source_ref) uniqueness constraint
                        # cannot collapse two distinct cases that both left
                        # source_ref blank.
                        source_ref=(case.source_ref or f"authored-{index}")[:255],
                        scenario=case.scenario,
                        prompt_inputs=case.prompt_inputs,
                        solution_criteria=case.solution_criteria,
                        label=case.label,
                    )
                    for index, case in enumerate(cases, start=1)
                ]
            )
        return suite.id

    def suite_dataset_hash(self, *, suite_id, workspace_id) -> str:
        """The suite's fingerprint AS IT STANDS NOW.

        Compared against a run's stored hash, this is what lets the panel say
        "this suite has changed since that run" instead of quietly presenting
        two incomparable scores next to each other.
        """
        from infrastructure.persistence.evaluation.models import EvalCase

        from infrastructure.persistence.evaluation.models import EvalSuite

        rows = list(
            EvalCase.objects.filter(suite_id=suite_id, workspace_id=workspace_id).values(
                "id", "scenario", "prompt_inputs", "solution_criteria"
            )
        )
        suite = EvalSuite.objects.filter(id=suite_id, workspace_id=workspace_id).only("system_prompt").first()
        return _fingerprint_rows(rows, system_prompt=suite.system_prompt if suite else "")

    def list_runs(self, *, workspace_id: str, limit: int = 25):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(workspace_id=workspace_id).select_related("suite").order_by("-created_at")[:limit]

    def get_run(self, *, run_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalRun

        return EvalRun.objects.filter(id=run_id, workspace_id=workspace_id).select_related("suite").first()

    def results_for(self, *, run_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        return (
            EvalCaseResult.objects.filter(run_id=run_id, workspace_id=workspace_id)
            .select_related("case")
            .order_by("created_at")
        )

    def get_result(self, *, result_id: str, workspace_id: str):
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        return (
            EvalCaseResult.objects.filter(id=result_id, workspace_id=workspace_id)
            .select_related("run", "case", "deep_run")
            .first()
        )

    # ── writes during a run ─────────────────────────────────────────────────

    def record_result(self, *, run, execution) -> None:
        from infrastructure.persistence.evaluation.models import EvalCaseResult

        EvalCaseResult.objects.update_or_create(
            run=run,
            case_id=execution.case.case_id,
            defaults={
                "workspace_id": run.workspace_id,
                "axis_verdicts": execution.axis_verdicts,
                "judge_reasoning": execution.reasoning,
                "judge_strengths": execution.strengths,
                "judge_weaknesses": execution.weaknesses,
                "output": (execution.outcome.output or "")[:20000],
                "failure_reason": execution.failure_reason,
                "cost_usd": Decimal(str(round(execution.cost_usd, 6))),
                "deep_run_id": execution.outcome.deep_run_id,
            },
        )

    def mark_progress(self, *, run, completed: int, cost_usd: float) -> None:
        from infrastructure.persistence.evaluation.models import EvalRun

        EvalRun.objects.filter(pk=run.pk).update(
            cases_completed=completed,
            cost_usd=Decimal(str(round(cost_usd, 6))),
            status=EvalRun.Status.RUNNING,
        )

    # ── concurrent-safe accounting ──────────────────────────────────────────
    #
    # Cases now execute in PARALLEL, so every counter below is written with an
    # F() expression rather than read-modify-write. Read-modify-write is correct
    # only while exactly one worker touches a run; with a fan-out, two workers
    # finishing at once both read `cases_completed = 40`, both write 41, and the
    # run silently loses a case — for a COST field that means under-reporting
    # real money spent.

    def accrue(self, *, run_id, cost_usd: float) -> tuple[int, Decimal]:
        """Atomically add one case's cost and bump the completed counter.

        Returns the run's (completed, cost) AFTER this case, read back in the
        same breath so the caller can decide about the cap and finalisation
        from post-increment values rather than its own stale copy.
        """
        from django.db.models import F

        from infrastructure.persistence.evaluation.models import EvalRun

        EvalRun.objects.filter(pk=run_id).update(
            cases_completed=F("cases_completed") + 1,
            cost_usd=F("cost_usd") + Decimal(str(round(cost_usd, 6))),
        )
        row = EvalRun.objects.filter(pk=run_id).values("cases_completed", "cost_usd").first()
        if row is None:
            return 0, Decimal(0)
        return int(row["cases_completed"]), Decimal(row["cost_usd"])

    def spend_so_far(self, *, run_id) -> Decimal:
        from infrastructure.persistence.evaluation.models import EvalRun

        row = EvalRun.objects.filter(pk=run_id).values("cost_usd").first()
        return Decimal(row["cost_usd"]) if row else Decimal(0)

    def claim_terminal_state(self, *, run_id, status, last_error: str = "") -> bool:
        """Move a run to a terminal state, exactly once.

        With N workers racing to finish the last case, several can observe
        "completed == total" simultaneously. The conditional UPDATE is the
        claim: it only matches a run still in a non-terminal state, so the
        database picks one winner and `.update()` returns 0 for the losers.

        Doing this with an if-then-save would let two workers both write
        `finished_at`, and — worse — both fire whatever finalisation follows.
        """
        from django.utils import timezone

        from infrastructure.persistence.evaluation.models import EvalRun

        claimed = EvalRun.objects.filter(
            pk=run_id,
            status__in=(EvalRun.Status.PENDING, EvalRun.Status.RUNNING),
        ).update(status=status, finished_at=timezone.now(), last_error=last_error)
        return bool(claimed)

    def mark_running(self, *, run_id) -> None:
        from django.utils import timezone

        from infrastructure.persistence.evaluation.models import EvalRun

        EvalRun.objects.filter(pk=run_id, status=EvalRun.Status.PENDING).update(
            status=EvalRun.Status.RUNNING, started_at=timezone.now()
        )

    def stalled_run_ids(self, *, older_than) -> list[str]:
        """Runs stuck mid-flight with nothing having happened for a while.

        A fan-out has a failure mode a single task does not: if the dispatched
        case tasks are lost — broker eviction, a worker killed between ack and
        execution — nothing is left to finish the run, and it sits at RUNNING
        for ever showing a half-finished bar. Nobody is coming; something has to
        notice. Silence is not success.
        """
        from django.db.models import Max, Q

        from infrastructure.persistence.evaluation.models import EvalRun

        rows = (
            EvalRun.objects.filter(status__in=(EvalRun.Status.PENDING, EvalRun.Status.RUNNING))
            .annotate(last_result_at=Max("results__created_at"))
            .filter(Q(last_result_at__lt=older_than) | Q(last_result_at__isnull=True, created_at__lt=older_than))
            .values_list("id", flat=True)
        )
        return [str(pk) for pk in rows]

    # ── aggregation ─────────────────────────────────────────────────────────

    def axis_evidence(self, *, run_id: str, workspace_id: str, axes: list[str]) -> list[AxisEvidence]:
        """Per-axis passed/measured for a run.

        ``measured`` counts only results where the axis actually has a verdict.
        An axis nobody assessed must not inflate the denominator — that is how a
        suite reports a 40% pass rate when 60% of cases were never graded on
        that axis at all.
        """
        rows = self.results_for(run_id=run_id, workspace_id=workspace_id)
        tallies = {axis: [0, 0] for axis in axes}  # axis -> [passed, measured]
        for row in rows:
            verdicts = row.axis_verdicts or {}
            for axis in axes:
                if axis not in verdicts:
                    continue
                tallies[axis][1] += 1
                if bool(verdicts[axis]):
                    tallies[axis][0] += 1
        return [
            AxisEvidence(axis=axis, passed=passed, measured=measured) for axis, (passed, measured) in tallies.items()
        ]


def _fingerprint_rows(rows, *, system_prompt: str = "") -> str:
    """Fingerprint ORM `.values()` dicts via the framework-free domain function."""
    return fingerprint(
        [
            CaseFingerprintInput(
                case_id=str(row["id"]),
                scenario=row["scenario"] or "",
                prompt_inputs=row["prompt_inputs"] or {},
                solution_criteria=list(row["solution_criteria"] or []),
            )
            for row in rows
        ],
        system_prompt=system_prompt,
    )


def _to_case_input(row) -> EvalCaseInput:
    return EvalCaseInput(
        case_id=str(row.id),
        scenario=row.scenario,
        prompt_inputs=row.prompt_inputs or {},
        solution_criteria=list(row.solution_criteria or []),
        label=row.label,
    )


__all__ = ["DjangoEvalRepository"]
