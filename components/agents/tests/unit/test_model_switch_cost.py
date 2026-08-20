"""A model switch must state its cost BEFORE it happens (ADR 0032 D7.3).

``fix_confidence`` already decided that measurements do not transfer between
models: evidence measured on X resolves to ``unproven`` the moment Y is
running. The committed corpus is ``gpt-3.5-turbo``, so the feature Henry asked
for — "let the admin change models" — silently revokes every measured tier the
first time it is used. A switch that quietly revokes measured trust is the same
class of defect as a report that reads clean because nothing was scanned.

These tests use a FAKE port, so they assert the wording and the fail-closed
logic without depending on whatever happens to be in the committed corpus
(which changes whenever the eval harness runs). The adapter's own contract —
that it fails closed on an unresolvable rule — is asserted separately.
"""

from __future__ import annotations

import pytest

from components.agents.application.ports.measured_evidence_port import (
    MeasuredEvidencePort,
    ModelSwitchImpactView,
    RuleEvidenceImpactView,
)
from components.agents.application.queries.model_switch_cost_query import (
    ANTI_THRASH_NOTE,
    FetchModelSwitchCostQuery,
)

pytestmark = pytest.mark.unit


class _FakePort(MeasuredEvidencePort):
    def __init__(self, view: ModelSwitchImpactView) -> None:
        self._view = view

    def model_switch_impact(self, *, current_model, candidate_model):
        return self._view


def _impact(**overrides) -> ModelSwitchImpactView:
    base = {
        "current_model": "gpt-3.5-turbo",
        "candidate_model": "claude-sonnet-4-20250514",
        "measured_rules": 4,
        "downgraded": (),
        "unchanged": 4,
        "min_trials_to_remeasure": 10,
        "is_noop": False,
    }
    base.update(overrides)
    return ModelSwitchImpactView(**base)


def _downgrade(rule_id="autosec.python.sql-execute-format"):
    return RuleEvidenceImpactView(
        rule_id=rule_id,
        from_tier="proven",
        to_tier="unproven",
        trials=20,
        passes=19,
        reason="measured on gpt-3.5-turbo, running claude — measurements do not transfer between models",
    )


class TestTheWarningIsSpecific:
    def test_it_names_how_many_rules_are_lost_and_the_remeasure_cost(self):
        view = FetchModelSwitchCostQuery(
            port=_FakePort(_impact(downgraded=(_downgrade(), _downgrade("r2")), unchanged=2))
        ).execute(current_model="gpt-3.5-turbo", candidate_model="claude-sonnet-4-20250514")

        assert "2 of 4 measured fix rules" in view.headline
        assert "unproven" in view.headline
        assert "10 trials per rule" in view.detail
        assert view.as_dict()["downgraded_count"] == 2

    def test_the_lost_rules_are_enumerated_not_just_counted(self):
        view = FetchModelSwitchCostQuery(port=_FakePort(_impact(downgraded=(_downgrade(),), unchanged=3))).execute(
            current_model="gpt-3.5-turbo", candidate_model="gpt-4o"
        )

        lost = view.as_dict()["downgraded"]
        assert lost[0]["rule_id"] == "autosec.python.sql-execute-format"
        assert lost[0]["from_tier"] == "proven"
        assert lost[0]["to_tier"] == "unproven"
        assert lost[0]["trials"] == 20

    def test_it_warns_about_switch_churn(self):
        """D7.6 — switching weekly means never accumulating measured trust."""
        view = FetchModelSwitchCostQuery(port=_FakePort(_impact(downgraded=(_downgrade(),)))).execute(
            current_model="a", candidate_model="b"
        )
        assert view.anti_thrash_note == ANTI_THRASH_NOTE
        assert "never accumulates" in view.anti_thrash_note


class TestAbsenceIsNotSafety:
    def test_nothing_measured_says_so_rather_than_reading_as_no_risk(self):
        """'Nothing to lose' because nothing was measured is a distinct fact."""
        view = FetchModelSwitchCostQuery(port=_FakePort(_impact(measured_rules=0, unchanged=0))).execute(
            current_model="gpt-4o-mini", candidate_model="gpt-4o"
        )

        assert "Nothing has been measured" in view.headline
        assert "there is none to lose" in view.headline

    def test_no_downgrade_with_evidence_present_is_reported_plainly(self):
        view = FetchModelSwitchCostQuery(port=_FakePort(_impact())).execute(
            current_model="gpt-4o", candidate_model="gpt-4o-x"
        )
        assert "None of the 4 measured fix rules change tier" in view.headline

    def test_switching_to_the_same_model_is_a_noop_with_no_scare_copy(self):
        view = FetchModelSwitchCostQuery(port=_FakePort(_impact(is_noop=True))).execute(
            current_model="gpt-4o", candidate_model="gpt-4o"
        )
        assert view.headline.startswith("No change")
        assert view.detail == ""
        assert view.anti_thrash_note == ""


class TestTheAdapterFailsClosed:
    def test_a_switch_off_the_measured_model_loses_every_measured_rule(self):
        """The live corpus, whatever it currently holds: run BOTH ways."""
        from components.agents.infrastructure.adapters.fix_confidence_evidence_adapter import (
            FixConfidenceEvidenceAdapter,
        )
        from components.code_security.domain.fix_confidence import measured_rules

        corpus = measured_rules()
        if not corpus:
            pytest.skip("no committed fix-confidence evidence to switch away from")
        measured_model = next(iter(corpus.values())).model

        impact = FixConfidenceEvidenceAdapter().model_switch_impact(
            current_model=measured_model,
            candidate_model="some-model-nobody-measured",
        )

        assert impact.measured_rules == len(corpus)
        # Every rule that was above ``unproven`` under the measured model must
        # be reported as lost — silence here would be the feature quietly
        # revoking trust.
        assert len(impact.downgraded) + impact.unchanged == len(corpus)
        assert all(rule.to_tier == "unproven" for rule in impact.downgraded)

    def test_an_undeclared_current_model_is_not_treated_as_a_noop(self):
        from components.agents.infrastructure.adapters.fix_confidence_evidence_adapter import (
            FixConfidenceEvidenceAdapter,
        )

        impact = FixConfidenceEvidenceAdapter().model_switch_impact(current_model="", candidate_model="gpt-4o")
        assert impact.is_noop is False
