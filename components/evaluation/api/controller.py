"""EVALUATE — the read + run surface (ADR 0033, contract-frozen).

Every route takes its workspace from the URL and checks membership against
THAT workspace. Not a query parameter, not a request body: those were the two
shapes behind #450, where a caller could name any tenant they liked and no
URL-scoped permission class was in a position to notice.

Running an eval costs money, so RUN requires workspace ADMIN while reading
requires membership. Provenance is stricter again — owner-only, per the
existing DeepRun read-authz contract, which EVALUATE must not become a way
around.
"""

from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_kernel.infrastructure.support.workspace_access import (
    is_workspace_admin,
    is_workspace_member,
)

logger = logging.getLogger(__name__)


def _provider():
    """The composition root. The controller never names a concrete adapter —
    `test_cross_context_import_rules` enforces that, and it is the reason this
    file has no infrastructure imports at all."""
    from components.evaluation.application.providers.evaluation_provider import (
        get_evaluation_provider,
    )

    return get_evaluation_provider()


def _repo():
    return _provider().repository()


def _deny(message: str, code=status.HTTP_403_FORBIDDEN) -> Response:
    return Response({"error": message}, status=code)


class _WorkspaceScoped(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def _member_or_deny(self, request, workspace_id):
        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return _deny("You do not have access to this workspace.")
        return None

    def _admin_or_deny(self, request, workspace_id):
        if not is_workspace_admin(user=request.user, workspace_id=workspace_id):
            return _deny("Only workspace owners and admins can run an evaluation.")
        return None


class EvalSuiteListView(_WorkspaceScoped):
    def get(self, request, workspace_id):
        denied = self._member_or_deny(request, workspace_id)
        if denied:
            return denied

        from components.evaluation.domain.value_objects.claim_tier import MIN_OBSERVATIONS
        from components.evaluation.domain.value_objects.dataset_version import short

        workspace_availability = _provider().availability_reader()
        repo = _repo()
        suites = []
        for suite in repo.list_suites(workspace_id=workspace_id):
            latest = repo.latest_run_for(suite_id=str(suite.id), workspace_id=workspace_id)
            # Fingerprinted once per suite, not once per field that reads it.
            current_hash = repo.suite_dataset_hash(suite_id=str(suite.id), workspace_id=workspace_id)
            suites.append(
                {
                    "id": str(suite.id),
                    "name": suite.name,
                    "agent_type": suite.agent_type,
                    "origin": suite.origin,
                    "case_count": getattr(suite, "case_count", 0),
                    "axes": list(suite.axes or []),
                    "dataset_version": short(current_hash),
                    # True when the cases were edited after the last run, so the
                    # last score no longer describes the suite as it stands. Left
                    # False when there is no run to compare against — "unchanged"
                    # would be a claim, and there is nothing to claim it about.
                    "changed_since_last_run": bool(
                        latest and latest.dataset_hash and latest.dataset_hash != current_hash
                    ),
                    "last_run": (
                        {
                            "id": str(latest.id),
                            "status": latest.status,
                            "finished_at": latest.finished_at,
                            "model_slug": latest.model_slug,
                        }
                        if latest
                        else None
                    ),
                }
            )

        try:
            report = workspace_availability(workspace_id, required=MIN_OBSERVATIONS)
            availability = report.as_dict()
        except Exception:
            # Availability is advisory. If it cannot be computed the suites
            # still render — but say so rather than sending zeros, which would
            # read as "you have no history" when the truth is "we did not look".
            logger.exception("eval_availability_failed workspace=%s", workspace_id)
            availability = None

        return Response({"suites": suites, "availability": availability}, status=status.HTTP_200_OK)


class EvalEstimateView(_WorkspaceScoped):
    def get(self, request, workspace_id, suite_id):
        denied = self._member_or_deny(request, workspace_id)
        if denied:
            return denied

        from components.evaluation.application.services.cost_estimator import estimate_run_cost

        repo = _repo()
        suite = repo.get_suite(suite_id=suite_id, workspace_id=workspace_id)
        if suite is None:
            return _deny("Suite not found.", status.HTTP_404_NOT_FOUND)

        cases = len(repo.load_cases(suite_id=suite_id, workspace_id=workspace_id))
        model_slug = _model_for(workspace_id)
        estimate = estimate_run_cost(
            cases=cases,
            model_slug=model_slug,
            cap_usd=_cap_for(workspace_id),
            model_lookup=_provider().price_lookup(),
        )
        return Response(estimate.as_dict(), status=status.HTTP_200_OK)


class EvalRunCreateView(_WorkspaceScoped):
    def post(self, request, workspace_id, suite_id):
        denied = self._admin_or_deny(request, workspace_id)
        if denied:
            return denied

        from components.evaluation.application.services.cost_estimator import estimate_run_cost

        provider = _provider()
        repo = provider.repository()
        suite = repo.get_suite(suite_id=suite_id, workspace_id=workspace_id)
        if suite is None:
            return _deny("Suite not found.", status.HTTP_404_NOT_FOUND)

        cases = repo.load_cases(suite_id=suite_id, workspace_id=workspace_id)
        if not cases:
            return _deny(
                "This suite has no cases yet, so there is nothing to run.",
                status.HTTP_409_CONFLICT,
            )

        model_slug = _model_for(workspace_id)
        estimate = estimate_run_cost(
            cases=len(cases),
            model_slug=model_slug,
            cap_usd=_cap_for(workspace_id),
            model_lookup=provider.price_lookup(),
        )
        if not estimate.within_cap:
            return _deny(
                f"Estimated cost ${estimate.estimated_cost_usd:.4f} exceeds this "
                f"workspace's cap of ${estimate.cap_usd:.2f}.",
                status.HTTP_409_CONFLICT,
            )

        run = repo.create_run(
            workspace_id=workspace_id,
            suite=suite,
            agent_type=suite.agent_type,
            model_slug=model_slug,
        )

        job = provider.create_progress_job(workspace_id=workspace_id, run_id=run.id, title=f"Evaluating {suite.name}")
        if job is not None:
            run.background_job = job
            run.save(update_fields=["background_job"])

        provider.enqueue_run(str(run.id))

        return Response(
            {
                "run_id": str(run.id),
                "background_job_id": str(job.id) if job else None,
                "status": run.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class EvalRunListView(_WorkspaceScoped):
    def get(self, request, workspace_id):
        denied = self._member_or_deny(request, workspace_id)
        if denied:
            return denied

        runs = [_run_dict(run) for run in _repo().list_runs(workspace_id=workspace_id)]
        return Response({"runs": runs}, status=status.HTTP_200_OK)


class EvalRunDetailView(_WorkspaceScoped):
    def get(self, request, workspace_id, run_id):
        denied = self._member_or_deny(request, workspace_id)
        if denied:
            return denied

        repo = _repo()
        run = repo.get_run(run_id=run_id, workspace_id=workspace_id)
        if run is None:
            return _deny("Run not found.", status.HTTP_404_NOT_FOUND)


        axes = list(run.suite.axes or [])
        evidence = repo.axis_evidence(run_id=run_id, workspace_id=workspace_id, axes=axes)
        results = [
            {
                "id": str(row.id),
                "case_id": str(row.case_id),
                "scenario": row.case.scenario,
                "source_kind": row.case.source_kind,
                "source_ref": row.case.source_ref,
                "axis_verdicts": row.axis_verdicts or {},
                "judge_reasoning": row.judge_reasoning,
                "judge_strengths": row.judge_strengths or [],
                "judge_weaknesses": row.judge_weaknesses or [],
                "failure_reason": row.failure_reason,
                "deep_run_id": str(row.deep_run_id) if row.deep_run_id else None,
                "agreement": (
                    {
                        "second_judge_model_slug": row.second_judge_model_slug,
                        "verdicts": row.second_judge_verdicts,
                    }
                    if row.second_judge_verdicts
                    else None
                ),
            }
            for row in repo.results_for(run_id=run_id, workspace_id=workspace_id)
        ]

        return Response(
            {
                "run": {**_run_dict(run), "last_error": run.last_error},
                "axes": [e.as_dict() for e in evidence],
                "results": results,
            },
            status=status.HTTP_200_OK,
        )


class EvalProvenanceView(_WorkspaceScoped):
    """Owner-only, per the existing DeepRun read-authz contract."""

    def get(self, request, workspace_id, result_id):
        denied = self._member_or_deny(request, workspace_id)
        if denied:
            return denied

        repo = _repo()
        result = repo.get_result(result_id=result_id, workspace_id=workspace_id)
        if result is None:
            return _deny("Result not found.", status.HTTP_404_NOT_FOUND)

        deep_run = result.deep_run
        if deep_run is None:
            return _deny(
                "No agent run was recorded for this case, so there is nothing to show.",
                status.HTTP_404_NOT_FOUND,
            )

        if str(getattr(deep_run, "user_id", "")) != str(request.user.id) and not getattr(
            request.user, "is_staff", False
        ):
            return _deny("Run detail is owner-only.")

        logs = [
            {
                "event_type": log.event_type,
                "tool_name": log.tool_name,
                "model_used": log.model_used,
                "system_prompt": log.system_prompt,
                "user_prompt": log.user_prompt,
                "llm_response": log.llm_response,
                "created_at": getattr(log, "created_at", None),
            }
            for log in deep_run.logs.all().order_by("id")[:200]
        ]

        return Response(
            {
                "deep_run_id": str(deep_run.id),
                "status": deep_run.status,
                "last_error": deep_run.last_error,
                "logs": logs,
            },
            status=status.HTTP_200_OK,
        )


# ── helpers ─────────────────────────────────────────────────────────────────


def _run_dict(run) -> dict:
    from components.evaluation.domain.value_objects.dataset_version import short

    return {
        "id": str(run.id),
        # Which exact set of cases this score belongs to (ADR 0033 D13). Two
        # runs with different versions are two different exams; the panel uses
        # this to refuse a comparison rather than draw a misleading trend.
        "dataset_version": short(run.dataset_hash),
        "suite_id": str(run.suite_id),
        "suite_name": run.suite.name,
        "model_slug": run.model_slug,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "cases_total": run.cases_total,
        "cases_completed": run.cases_completed,
        "cost_usd": f"{run.cost_usd:.4f}",
    }


def _workspace_ai_config(workspace_id) -> dict:
    return _provider().workspace_ai_config(workspace_id)


def _model_for(workspace_id) -> str:
    return _workspace_ai_config(workspace_id).get("preferred_model") or "gpt-4o-mini"


def _cap_for(workspace_id):
    from decimal import Decimal

    cap = _workspace_ai_config(workspace_id).get("eval_cost_cap_usd")
    return Decimal(str(cap)) if cap else None
