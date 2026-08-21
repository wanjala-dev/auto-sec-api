"""The curated seed must be idempotent, tenant-scoped, and honest in its output.

Three failures this pins down, all of which this codebase has shipped before in
one form or another:

* A seed that prints SUCCESS while doing nothing. The counts are asserted, not
  the exit status.
* A re-run that duplicates rows. Every duplicate inflates the denominator of a
  pass rate, which is the false-denominator problem ADR 0032 exists to prevent.
* A ``--dry-run`` that writes. The whole point of the flag is to be safe to run
  against a customer's workspace.

The command is invoked as a ``Command`` INSTANCE rather than by name because
``components.evaluation.cli`` is not yet in ``INSTALLED_APPS`` — that one-line
registration belongs to the PR that lands the evaluation app wiring, and this
test must not depend on it having happened. ``call_command`` accepts an
instance, and the code path exercised is identical.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from components.evaluation.cli.management.commands.seed_eval_suite import (
    AGENT_TYPE,
    CURATED_TRIAGE_CASES,
    SUITE_NAME,
    Command,
)
from components.evaluation.domain.value_objects.axes import TRIAGE_AXIS_KEYS
from infrastructure.persistence.evaluation.models import EvalCase, EvalSuite

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

CASE_COUNT = len(CURATED_TRIAGE_CASES)


def seed(workspace, *extra_args) -> str:
    out = StringIO()
    call_command(Command(), "--workspace", str(workspace.id), *extra_args, stdout=out)
    return out.getvalue()


@pytest.fixture
def workspace(workspace_factory, user_factory):
    return workspace_factory(owner=user_factory())


class TestTheCuratedCatalogueItself:
    """Properties of the authored data, independent of the database."""

    def test_it_is_the_size_the_adr_asks_for(self):
        assert 6 <= CASE_COUNT <= 10

    def test_every_axis_is_exercised_by_at_least_one_case(self):
        """An axis no case exercises measures nothing (ADR 0033 D2)."""
        covered = {axis for case in CURATED_TRIAGE_CASES for axis in case.axes_exercised}

        assert covered == set(TRIAGE_AXIS_KEYS), f"axes with no curated case: {set(TRIAGE_AXIS_KEYS) - covered}"

    def test_slugs_are_unique(self):
        slugs = [case.slug for case in CURATED_TRIAGE_CASES]

        assert len(slugs) == len(set(slugs))

    def test_every_case_carries_one_to_four_criteria_and_a_scenario(self):
        for case in CURATED_TRIAGE_CASES:
            assert 1 <= len(case.solution_criteria) <= 4, case.slug
            assert case.scenario.strip(), case.slug
            assert case.prompt_inputs, case.slug


class TestSeeding:
    def test_it_creates_the_suite_and_every_case(self, workspace):
        output = seed(workspace)

        suite = EvalSuite.objects.get(workspace=workspace, name=SUITE_NAME)
        assert suite.agent_type == AGENT_TYPE
        assert suite.origin == EvalSuite.Origin.CURATED
        assert list(suite.axes) == list(TRIAGE_AXIS_KEYS)
        assert suite.cases.count() == CASE_COUNT
        assert "created" in output

    def test_every_case_is_stored_as_curated_and_unlabelled(self, workspace):
        seed(workspace)

        cases = EvalCase.objects.filter(workspace=workspace)
        assert cases.count() == CASE_COUNT
        for case in cases:
            assert case.source_kind == EvalCase.SourceKind.CURATED
            # Authored, not decided by a human — a fabricated GOOD/BAD here
            # would poison the judge-calibration set (D6a).
            assert case.label == EvalCase.Label.UNLABELLED
            assert 1 <= len(case.solution_criteria) <= 4
            assert case.scenario

    def test_the_criteria_persisted_are_the_ones_authored(self, workspace):
        seed(workspace)

        stored = EvalCase.objects.get(workspace=workspace, source_ref="dependency-bump-patch")
        authored = next(c for c in CURATED_TRIAGE_CASES if c.slug == "dependency-bump-patch")

        assert stored.solution_criteria == list(authored.solution_criteria)
        assert stored.prompt_inputs == authored.prompt_inputs

    def test_the_output_states_the_counts(self, workspace):
        output = seed(workspace)

        assert f"created={CASE_COUNT}" in output
        assert "already-present=0" in output
        assert f"total-in-suite={CASE_COUNT}" in output

    def test_the_output_states_the_claim_tier_rather_than_implying_a_verdict(self, workspace):
        """Eight cases is below D9's floor of ten. Saying so here is what stops
        the number being over-read on the panel later."""
        output = seed(workspace)

        assert "NOT MEASURED" in output
        assert "not a verdict" in output


class TestIdempotence:
    def test_re_running_creates_nothing_new(self, workspace):
        seed(workspace)
        second = seed(workspace)

        assert EvalSuite.objects.filter(workspace=workspace, name=SUITE_NAME).count() == 1
        assert EvalCase.objects.filter(workspace=workspace).count() == CASE_COUNT
        assert "created=0" in second
        assert f"already-present={CASE_COUNT}" in second

    def test_a_third_run_is_still_stable(self, workspace):
        seed(workspace)
        seed(workspace)
        seed(workspace)

        assert EvalCase.objects.filter(workspace=workspace).count() == CASE_COUNT

    def test_a_case_deleted_by_hand_is_restored_without_touching_the_rest(self, workspace):
        seed(workspace)
        EvalCase.objects.filter(workspace=workspace, source_ref="out-of-scope-request").delete()

        output = seed(workspace)

        assert "created=1" in output
        assert f"already-present={CASE_COUNT - 1}" in output
        assert EvalCase.objects.filter(workspace=workspace).count() == CASE_COUNT


class TestDryRun:
    def test_it_writes_nothing_on_an_empty_workspace(self, workspace):
        output = seed(workspace, "--dry-run")

        assert EvalSuite.objects.filter(workspace=workspace).count() == 0
        assert EvalCase.objects.filter(workspace=workspace).count() == 0
        assert f"would-create={CASE_COUNT}" in output
        assert "nothing was written" in output

    def test_it_reports_an_already_seeded_workspace_as_present(self, workspace):
        seed(workspace)

        output = seed(workspace, "--dry-run")

        assert "would-create=0" in output
        assert f"already-present={CASE_COUNT}" in output
        assert EvalCase.objects.filter(workspace=workspace).count() == CASE_COUNT


class TestScopingAndBadInput:
    def test_seeding_one_workspace_leaves_another_untouched(self, workspace_factory, user_factory):
        """The pooled tier has no database boundary behind a missing filter."""
        first = workspace_factory(owner=user_factory())
        second = workspace_factory(owner=user_factory())

        seed(first)

        assert EvalCase.objects.filter(workspace=first).count() == CASE_COUNT
        assert EvalCase.objects.filter(workspace=second).count() == 0

    def test_two_workspaces_can_each_hold_the_curated_suite(self, workspace_factory, user_factory):
        first = workspace_factory(owner=user_factory())
        second = workspace_factory(owner=user_factory())

        seed(first)
        seed(second)

        assert EvalSuite.objects.filter(name=SUITE_NAME).count() == 2
        assert EvalCase.objects.filter(workspace=second).count() == CASE_COUNT

    def test_an_unknown_workspace_fails_closed(self):
        out = StringIO()
        with pytest.raises(CommandError) as excinfo:
            call_command(Command(), "--workspace", "11111111-1111-1111-1111-111111111111", stdout=out)

        assert "No workspace" in str(excinfo.value)
        assert EvalSuite.objects.count() == 0

    def test_a_non_uuid_workspace_is_rejected_with_the_value(self):
        with pytest.raises(CommandError) as excinfo:
            call_command(Command(), "--workspace", "not-a-uuid", stdout=StringIO())

        assert "not-a-uuid" in str(excinfo.value)

    def test_an_existing_suite_with_different_axes_is_flagged_not_rewritten(self, workspace):
        """Rewriting the axis list would re-interpret results already recorded
        against the old one — the reason axes are stored per suite."""
        EvalSuite.objects.create(
            workspace=workspace,
            name=SUITE_NAME,
            agent_type=AGENT_TYPE,
            origin=EvalSuite.Origin.CURATED,
            axes=["grounded"],
        )

        output = seed(workspace)

        suite = EvalSuite.objects.get(workspace=workspace, name=SUITE_NAME)
        assert list(suite.axes) == ["grounded"], "the stored axis set must not be silently rewritten"
        assert "Left unchanged" in output
