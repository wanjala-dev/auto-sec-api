"""The bridge between the mechanical checks and the port.

The checks themselves are tested in `test_verifiers.py`. What is at stake HERE
is the translation, and it has exactly one way to go badly: NOT MEASURED
arriving at the port as `False`. `Outcome.NOT_MEASURED` is falsy-adjacent in
every careless spelling of this mapping — `passed=result.passed` alone gets it
wrong, because `VerificationResult.passed` is False for both a real failure and
an unmeasurable one. That collapse would turn "we could not check" into a
reported defect on a customer's agent.

The other half is the inventory. A verifier is only as honest as the ground
truth it compares against, so these tests pin where each one comes from and
what happens when it is missing.
"""

from __future__ import annotations

import pytest

from components.evaluation.application.ports.eval_ports import AgentOutcome, EvalCaseInput
from components.evaluation.domain.services.verifiers import Outcome, VerificationResult
from components.evaluation.infrastructure.adapters.verifier_adapter import (
    DETERMINISTIC_AXES,
    DeterministicVerifierAdapter,
)

pytestmark = [pytest.mark.unit]

PATCH = """--- a/app/config.py
+++ b/app/config.py
@@ -1,3 +1,3 @@
-DEBUG = True
+DEBUG = False
"""


def _adapter(assets=()):
    return DeterministicVerifierAdapter(workspace_id="ws-1", asset_inventory_reader=lambda _ws: tuple(assets))


def _case(**inputs):
    return EvalCaseInput(case_id="c1", scenario="public bucket", prompt_inputs=dict(inputs), solution_criteria=[])


class TestRouting:
    def test_only_the_mechanical_axes_are_claimed(self):
        adapter = _adapter()

        assert adapter.supports("fix_applies")
        assert adapter.supports("no_fabricated_asset")
        # Everything else must fall through to the judge. Claiming an axis it
        # cannot actually check would silently stop that axis being graded.
        assert not adapter.supports("grounded")
        assert not adapter.supports("severity_sound")

    def test_an_unclaimed_axis_reaching_verify_is_unmeasured_not_passed(self):
        """Only reachable if `supports()` and the dispatch drift apart. It must
        fail safe toward NOT MEASURED, not toward a free pass."""
        verdict = _adapter().verify(axis="grounded", case=_case(), outcome=AgentOutcome(output="x"))

        assert verdict.passed is None
        assert "grounded" in verdict.reason


class TestNotMeasuredSurvivesTheTranslation:
    def test_no_asset_inventory_is_none_not_false(self):
        """An empty inventory makes every reference look fabricated. That is
        our gap, and scoring the agent for it manufactures a failure."""
        verdict = _adapter(assets=()).verify(
            axis="no_fabricated_asset",
            case=_case(),
            outcome=AgentOutcome(output="the bucket arn:aws:s3:::prod-logs is public"),
        )

        assert verdict.passed is None, "an empty inventory must not read as a fabrication"
        assert verdict.reason

    def test_a_case_declaring_no_target_files_is_none_not_false(self):
        verdict = _adapter().verify(
            axis="fix_applies", case=_case(title="no files here"), outcome=AgentOutcome(output=PATCH)
        )

        assert verdict.passed is None

    def test_the_three_domain_states_map_to_true_false_none(self):
        from components.evaluation.infrastructure.adapters.verifier_adapter import _to_verdict

        assert _to_verdict(VerificationResult("a", Outcome.PASSED, "")).passed is True
        assert _to_verdict(VerificationResult("a", Outcome.FAILED, "")).passed is False
        # The one that matters.
        assert _to_verdict(VerificationResult("a", Outcome.NOT_MEASURED, "")).passed is None


class TestRealVerdicts:
    def test_a_referenced_asset_that_exists_passes(self):
        verdict = _adapter(assets=("arn:aws:s3:::prod-logs",)).verify(
            axis="no_fabricated_asset",
            case=_case(),
            outcome=AgentOutcome(output="arn:aws:s3:::prod-logs is world-readable"),
        )

        assert verdict.passed is True

    def test_an_invented_asset_fails(self):
        verdict = _adapter(assets=("arn:aws:s3:::prod-logs",)).verify(
            axis="no_fabricated_asset",
            case=_case(),
            outcome=AgentOutcome(output="arn:aws:s3:::totally-made-up is world-readable"),
        )

        assert verdict.passed is False
        assert verdict.reason

    def test_a_patch_against_a_declared_file_passes(self):
        verdict = _adapter().verify(
            axis="fix_applies", case=_case(file_path="app/config.py"), outcome=AgentOutcome(output=PATCH)
        )

        assert verdict.passed is True

    def test_prose_that_is_not_a_diff_fails(self):
        verdict = _adapter().verify(
            axis="fix_applies",
            case=_case(file_path="app/config.py"),
            outcome=AgentOutcome(output="You should set DEBUG to False in the config."),
        )

        assert verdict.passed is False


class TestTargetFileDiscovery:
    def test_the_paths_are_read_from_any_of_the_spellings_scanners_use(self):
        from components.evaluation.infrastructure.adapters.verifier_adapter import (
            _declared_target_files,
        )

        assert _declared_target_files(_case(file_path="a.py")) == ("a.py",)
        assert _declared_target_files(_case(target_files=["a.py", "b.py"])) == ("a.py", "b.py")
        assert _declared_target_files(_case(location="a.py")) == ("a.py",)

    def test_the_same_path_under_two_keys_is_not_counted_twice(self):
        from components.evaluation.infrastructure.adapters.verifier_adapter import (
            _declared_target_files,
        )

        assert _declared_target_files(_case(file_path="a.py", path="a.py")) == ("a.py",)

    def test_nothing_declared_is_none_rather_than_an_empty_tuple(self):
        """The verifier words these two differently — "none was supplied" vs
        "the inventory is empty" — and an operator reads the difference."""
        from components.evaluation.infrastructure.adapters.verifier_adapter import (
            _declared_target_files,
        )

        assert _declared_target_files(_case(title="x")) is None
        assert _declared_target_files(_case(file_path="   ")) is None


class TestResilience:
    def test_a_raising_inventory_read_leaves_the_axis_unmeasured(self):
        def _explode(_ws):
            raise RuntimeError("db down")

        adapter = DeterministicVerifierAdapter(workspace_id="ws-1", asset_inventory_reader=_explode)

        verdict = adapter.verify(axis="no_fabricated_asset", case=_case(), outcome=AgentOutcome(output="x"))

        assert verdict.passed is None
        assert "db down" in verdict.reason

    def test_the_inventory_is_read_once_per_run_not_once_per_case(self):
        """A 50-case suite must not fire 50 identical queries."""
        calls = []

        def _reader(ws):
            calls.append(ws)
            return ("arn:aws:s3:::prod-logs",)

        adapter = DeterministicVerifierAdapter(workspace_id="ws-1", asset_inventory_reader=_reader)
        for _ in range(5):
            adapter.verify(axis="no_fabricated_asset", case=_case(), outcome=AgentOutcome(output="x"))

        assert len(calls) == 1


def test_the_deterministic_axis_list_is_what_supports_actually_dispatches():
    """Guards the drift that `test_an_unclaimed_axis...` only fails safe on."""
    adapter = _adapter(assets=("arn:aws:s3:::x",))
    for axis in DETERMINISTIC_AXES:
        verdict = adapter.verify(axis=axis, case=_case(file_path="a.py"), outcome=AgentOutcome(output=PATCH))
        assert "No deterministic check is registered" not in verdict.reason
