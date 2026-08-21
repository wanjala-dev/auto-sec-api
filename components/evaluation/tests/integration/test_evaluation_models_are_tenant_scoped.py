"""Every evaluation row belongs to exactly one workspace — enforced, not assumed.

The surface this replaces read its reports off the filesystem
(``docs/eval-reports/*.json``), so every workspace saw the same 30 files baked
into the image. Evaluation results are a customer's own quality evidence: they
are tenant data.

On the pooled tier there is no database boundary behind a missing
``workspace_id`` filter — the filter IS the boundary. So this is a fitness
function over the schema rather than a test of one query: a future model added
to this app without a workspace FK fails here, at the point it is added, rather
than in an incident.
"""

from __future__ import annotations

import pytest
from django.apps import apps

from infrastructure.persistence.evaluation.models import (
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalSuite,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestSchemaIsTenantScoped:
    def test_every_model_in_the_app_has_a_workspace_fk(self):
        offenders = []
        for model in apps.get_app_config("evaluation").get_models():
            field_names = {f.name for f in model._meta.get_fields()}
            if "workspace" not in field_names:
                offenders.append(model.__name__)

        assert not offenders, (
            f"evaluation models with no workspace FK: {offenders}. On the pooled tier the "
            "filter IS the tenant boundary — a row that cannot be scoped cannot be served."
        )

    def test_the_workspace_fk_is_not_nullable(self):
        """A nullable tenant column is a row that belongs to everyone."""
        nullable = []
        for model in apps.get_app_config("evaluation").get_models():
            try:
                field = model._meta.get_field("workspace")
            except Exception:  # covered by the test above
                continue
            if field.null:
                nullable.append(model.__name__)

        assert not nullable, f"evaluation models with a nullable workspace FK: {nullable}"


class TestSuiteConstraints:
    def test_two_workspaces_may_use_the_same_suite_name(self, workspace_factory, user_factory):
        """Names are scoped, not global. A global unique name would leak the
        existence of another tenant's suite through a constraint error."""
        ws_a = workspace_factory(owner=user_factory())
        ws_b = workspace_factory(owner=user_factory())

        EvalSuite.objects.create(workspace=ws_a, name="Triage baseline", agent_type="triage")
        EvalSuite.objects.create(workspace=ws_b, name="Triage baseline", agent_type="triage")

        assert EvalSuite.objects.filter(name="Triage baseline").count() == 2

    def test_one_workspace_cannot_reuse_a_suite_name(self, workspace_factory, user_factory):
        from django.db.utils import IntegrityError

        ws = workspace_factory(owner=user_factory())
        EvalSuite.objects.create(workspace=ws, name="Triage baseline", agent_type="triage")

        with pytest.raises(IntegrityError):
            EvalSuite.objects.create(workspace=ws, name="Triage baseline", agent_type="triage")


class TestCaseAndResultIntegrity:
    @pytest.fixture
    def suite(self, workspace_factory, user_factory):
        ws = workspace_factory(owner=user_factory())
        return EvalSuite.objects.create(
            workspace=ws,
            name="Triage baseline",
            agent_type="triage",
            axes=["grounded", "fix_applies"],
        )

    def test_the_same_source_cannot_be_mined_twice_into_one_suite(self, suite):
        """Mining is re-runnable. Without this, every re-mine inflates the
        denominator with duplicates and the pass rate becomes meaningless."""
        from django.db.utils import IntegrityError

        EvalCase.objects.create(
            suite=suite,
            workspace=suite.workspace,
            source_kind=EvalCase.SourceKind.SIGN_OFF,
            source_ref="signoff-123",
        )

        with pytest.raises(IntegrityError):
            EvalCase.objects.create(
                suite=suite,
                workspace=suite.workspace,
                source_kind=EvalCase.SourceKind.SIGN_OFF,
                source_ref="signoff-123",
            )

    def test_a_run_records_the_model_that_produced_it(self, suite):
        """ADR 0032: measurements do not transfer between models. A result
        without its model cannot be interpreted or safely compared."""
        run = EvalRun.objects.create(
            workspace=suite.workspace,
            suite=suite,
            agent_type="triage",
            model_slug="gpt-4o-mini",
        )

        assert run.model_slug == "gpt-4o-mini"
        assert run.status == EvalRun.Status.PENDING

    def test_one_result_per_case_per_run(self, suite):
        from django.db.utils import IntegrityError

        case = EvalCase.objects.create(
            suite=suite,
            workspace=suite.workspace,
            source_kind=EvalCase.SourceKind.SIGN_OFF,
            source_ref="signoff-1",
        )
        run = EvalRun.objects.create(
            workspace=suite.workspace, suite=suite, agent_type="triage", model_slug="gpt-4o-mini"
        )
        EvalCaseResult.objects.create(run=run, case=case, workspace=suite.workspace, axis_verdicts={"grounded": True})

        with pytest.raises(IntegrityError):
            EvalCaseResult.objects.create(run=run, case=case, workspace=suite.workspace)

    def test_a_result_can_carry_its_provenance_link(self, suite):
        """The deep_run FK is how a failed case becomes actionable (D4)."""
        case = EvalCase.objects.create(
            suite=suite,
            workspace=suite.workspace,
            source_kind=EvalCase.SourceKind.SIGN_OFF,
            source_ref="signoff-2",
        )
        run = EvalRun.objects.create(
            workspace=suite.workspace, suite=suite, agent_type="triage", model_slug="gpt-4o-mini"
        )
        result = EvalCaseResult.objects.create(
            run=run, case=case, workspace=suite.workspace, axis_verdicts={"grounded": False}
        )

        assert "deep_run" in {f.name for f in result._meta.get_fields()}
        assert result.deep_run is None  # nullable: a case can fail before a run exists
