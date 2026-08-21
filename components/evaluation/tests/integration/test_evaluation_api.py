"""The EVALUATE API, from the outside.

Two things are being asserted, and only one of them is the feature.

The feature is that the payload matches the frozen contract — in particular
that ``pass_rate`` is ``null`` rather than ``0`` below the measurement floor,
because the frontend renders straight from this and a coerced zero would paint
a catastrophe onto three observations.

The other is the tenant boundary. Evaluation results are a customer's own
quality evidence. Every route takes its workspace from the URL precisely so a
permission class can guard it — the shape #450 fixed — and these tests prove
an outsider gets 403 while a member still gets their own data.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
)
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

AXES = ["grounded", "fix_applies"]


def _member(workspace, user, role="admin"):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


@pytest.fixture
def tenants(workspace_factory, user_factory):
    alice, bob = user_factory(), user_factory()
    ws_a = workspace_factory(owner=user_factory())
    ws_b = workspace_factory(owner=user_factory())
    _member(ws_a, alice)
    _member(ws_b, bob)

    suite = EvalSuite.objects.create(workspace=ws_a, name="Triage baseline", agent_type="triage", axes=AXES)
    case = EvalCase.objects.create(
        suite=suite,
        workspace=ws_a,
        source_kind=EvalCase.SourceKind.CURATED,
        source_ref="curated-1",
        scenario="public bucket",
    )
    run = EvalRun.objects.create(
        workspace=ws_a,
        suite=suite,
        agent_type="triage",
        model_slug="gpt-4o-mini",
        cases_total=1,
        cases_completed=1,
        status=EvalRun.Status.COMPLETED,
    )
    result = EvalCaseResult.objects.create(
        run=run,
        case=case,
        workspace=ws_a,
        axis_verdicts={"grounded": True},
        judge_reasoning="it cited the bucket",
    )
    return {
        "alice": alice,
        "bob": bob,
        "ws_a": ws_a,
        "ws_b": ws_b,
        "suite": suite,
        "case": case,
        "run": run,
        "result": result,
    }


def _as(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class TestTenantBoundary:
    def test_an_outsider_cannot_list_another_workspaces_suites(self, tenants):
        url = reverse("evaluation:eval-suites", kwargs={"workspace_id": tenants["ws_a"].id})

        assert _as(tenants["bob"]).get(url).status_code == 403

    def test_a_member_lists_their_own(self, tenants):
        url = reverse("evaluation:eval-suites", kwargs={"workspace_id": tenants["ws_a"].id})

        response = _as(tenants["alice"]).get(url)

        assert response.status_code == 200
        assert response.data["suites"][0]["name"] == "Triage baseline"

    def test_an_outsider_cannot_read_a_run(self, tenants):
        url = reverse(
            "evaluation:eval-run-detail",
            kwargs={"workspace_id": tenants["ws_a"].id, "run_id": tenants["run"].id},
        )

        assert _as(tenants["bob"]).get(url).status_code == 403

    def test_an_outsider_cannot_start_a_run(self, tenants):
        url = reverse(
            "evaluation:eval-run-create",
            kwargs={"workspace_id": tenants["ws_a"].id, "suite_id": tenants["suite"].id},
        )

        assert _as(tenants["bob"]).post(url).status_code == 403

    def test_a_plain_member_cannot_start_a_run(self, tenants, user_factory):
        """Running costs money, so RUN is admin-only while reading is not."""
        viewer = user_factory()
        _member(tenants["ws_a"], viewer, role="member")
        url = reverse(
            "evaluation:eval-run-create",
            kwargs={"workspace_id": tenants["ws_a"].id, "suite_id": tenants["suite"].id},
        )

        response = _as(viewer).post(url)

        assert response.status_code == 403
        assert "admin" in response.data["error"].lower()


class TestRunDetailHonesty:
    def test_pass_rate_is_null_below_the_floor_not_zero(self, tenants):
        """The contract's load-bearing line. One observation is not 100%, and
        it is not 0% either — it is not a rate at all."""
        url = reverse(
            "evaluation:eval-run-detail",
            kwargs={"workspace_id": tenants["ws_a"].id, "run_id": tenants["run"].id},
        )

        response = _as(tenants["alice"]).get(url)

        grounded = next(a for a in response.data["axes"] if a["axis"] == "grounded")
        assert grounded["measured"] == 1
        assert grounded["pass_rate"] is None
        assert grounded["tier_label"] == "NOT MEASURED"
        assert grounded["may_conclude"] is False

    def test_an_unmeasured_axis_does_not_inflate_the_denominator(self, tenants):
        """`fix_applies` was never graded. It must count 0 measured, not 1
        measured-and-failed — that is how a suite reports a 50% pass rate for
        an axis it never assessed."""
        url = reverse(
            "evaluation:eval-run-detail",
            kwargs={"workspace_id": tenants["ws_a"].id, "run_id": tenants["run"].id},
        )

        response = _as(tenants["alice"]).get(url)

        fix_applies = next(a for a in response.data["axes"] if a["axis"] == "fix_applies")
        assert fix_applies["measured"] == 0
        assert fix_applies["passed"] == 0
        assert fix_applies["pass_rate"] is None

    def test_the_judges_reasoning_is_returned(self, tenants):
        url = reverse(
            "evaluation:eval-run-detail",
            kwargs={"workspace_id": tenants["ws_a"].id, "run_id": tenants["run"].id},
        )

        response = _as(tenants["alice"]).get(url)

        assert response.data["results"][0]["judge_reasoning"] == "it cited the bucket"


class TestEstimate:
    def test_the_estimate_states_its_assumptions(self, tenants):
        """An estimate whose basis is invisible is a guess with a dollar sign."""
        url = reverse(
            "evaluation:eval-estimate",
            kwargs={"workspace_id": tenants["ws_a"].id, "suite_id": tenants["suite"].id},
        )

        response = _as(tenants["alice"]).get(url)

        assert response.status_code == 200
        assert response.data["cases"] == 1
        assert "LLM calls per case" in response.data["assumptions"]


class TestProvenance:
    def test_a_result_with_no_run_says_so_rather_than_returning_an_empty_log(self, tenants):
        """An empty list reads as "the agent did nothing". The truth is that we
        did not capture it, and those are different facts."""
        url = reverse(
            "evaluation:eval-provenance",
            kwargs={"workspace_id": tenants["ws_a"].id, "result_id": tenants["result"].id},
        )

        response = _as(tenants["alice"]).get(url)

        assert response.status_code == 404
        assert "no agent run" in response.data["error"].lower()


class TestRunCreation:
    def test_an_empty_suite_refuses_rather_than_starting_a_pointless_run(
        self, tenants, workspace_factory, user_factory
    ):
        empty = EvalSuite.objects.create(workspace=tenants["ws_a"], name="Empty", agent_type="triage", axes=AXES)
        url = reverse(
            "evaluation:eval-run-create",
            kwargs={"workspace_id": tenants["ws_a"].id, "suite_id": empty.id},
        )

        response = _as(tenants["alice"]).post(url)

        assert response.status_code == 409
        assert "no cases" in response.data["error"].lower()
