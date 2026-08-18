"""The harness itself must classify correctly before its numbers mean anything.

Every case scripts the LLM (no network) and drives the REAL advisor + the REAL
verifier through ``run_fixture`` — the same objects production uses — so a
verdict here is a verdict about the production choreography, not about a stub.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.agents.infrastructure.evaluation.sast_fix_eval import (
    load_fixtures,
    run_fixture,
    summarize,
)
from components.code_security.application.sast_fix_advisor_service import SastFixAdvisor

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _ScriptedLlm:
    """Returns the queued responses in order — the re-advise loop pops twice."""

    def __init__(self, *responses: dict):
        self._queue = [json.dumps(r) for r in responses]
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        content = self._queue.pop(0) if self._queue else self._queue_exhausted()

        class _Resp:
            pass

        resp = _Resp()
        resp.content = content
        return resp

    @staticmethod
    def _queue_exhausted():
        raise AssertionError("scripted LLM called more times than the case expects")


def _fixture(fixture_id: str):
    matches = [f for f in load_fixtures(FIXTURES_DIR) if f.id == fixture_id]
    assert matches, f"fixture {fixture_id} missing"
    return matches[0]


def _advisor(llm, fixture):
    return SastFixAdvisor(llm_port=llm, file_reader=lambda ws, repo, path, ref: fixture.source_content)


def _suggestion(fix_before: str, fix_after: str, *, confidence: str = "high", fixture=None) -> dict:
    where = f"{fixture.path} for rule {fixture.rule_id}" if fixture else "the flagged file"
    return {
        "likely_cause": f"The flagged line in {where} interpolates dynamic input into a sensitive call.",
        "suggested_fix": f"Apply the remediation for {fixture.rule_id} at {fixture.path}." if fixture else "Fix it.",
        "fix_before": fix_before,
        "fix_after": fix_after,
        "confidence": confidence,
    }


CREATE_SCHEMA_LINE = 'cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")'
CORRECT_IDENTIFIER_FIX = (
    'from psycopg import sql\ncursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))'
)
WRONG_IDENTIFIER_FIX = 'cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))'


class TestClassAOutcomes:
    def test_a_correct_fix_machine_passes(self):
        fixture = _fixture("sql-create-schema-fstring")
        llm = _ScriptedLlm(_suggestion(CREATE_SCHEMA_LINE, CORRECT_IDENTIFIER_FIX, fixture=fixture))
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.verification == "verified"
        assert result.outcome == "machine_pass"
        assert result.gates["shape"] == "pass"
        assert result.gates["rescan"].startswith("skipped")

    def test_the_dogfood_wrong_shape_is_gated_after_one_readvise(self):
        """#866's exact patch, twice: the harness must record the L3 rejection,
        the single re-advise, and the unverified label — the production loop."""
        fixture = _fixture("sql-create-schema-fstring")
        llm = _ScriptedLlm(
            _suggestion(CREATE_SCHEMA_LINE, WRONG_IDENTIFIER_FIX, fixture=fixture),
            _suggestion(CREATE_SCHEMA_LINE, WRONG_IDENTIFIER_FIX, fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.readvised is True
        assert llm.calls == 2
        assert result.verification == "unverified"
        assert result.outcome == "gated"
        assert result.gates["shape"].startswith("fail")

    def test_a_wrong_first_attempt_recovered_on_readvise_passes(self):
        fixture = _fixture("sql-create-schema-fstring")
        llm = _ScriptedLlm(
            _suggestion(CREATE_SCHEMA_LINE, WRONG_IDENTIFIER_FIX, fixture=fixture),
            _suggestion(CREATE_SCHEMA_LINE, CORRECT_IDENTIFIER_FIX, fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.readvised is True
        assert result.verification == "verified"
        assert result.outcome == "machine_pass"

    def test_the_advisor_itself_refuses_a_fix_for_the_neighboring_statement(self):
        """Observed live (candidate-contrastive run): the model fixed the
        CREATE SCHEMA line for a finding flagging the SET line below it.
        With the flagged region known, the advisor's grounding gate now
        refuses the suggestion outright — the neighboring statement never
        becomes an artifact."""
        fixture = _fixture("sql-set-search-path-fstring")
        llm = _ScriptedLlm(
            _suggestion(CREATE_SCHEMA_LINE, CORRECT_IDENTIFIER_FIX, fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "no_artifact"

    def test_the_span_gate_backstops_when_the_flagged_region_is_unknown(self):
        """A failed file read degrades the advisor to snippet-only grounding
        (which the neighboring line satisfies — it sits inside the ±3
        context); the harness span gate is the layer that still records the
        mismatch."""
        fixture = _fixture("sql-set-search-path-fstring")
        llm = _ScriptedLlm(
            _suggestion(CREATE_SCHEMA_LINE, CORRECT_IDENTIFIER_FIX, fixture=fixture),
        )
        advisor = SastFixAdvisor(llm_port=llm, file_reader=lambda ws, repo, path, ref: None)
        result = run_fixture(fixture, advisor)
        assert result.gates["targets_flagged_span"].startswith("fail")
        assert result.outcome == "gated"

    def test_a_suppression_comment_fails_the_anti_gaming_gate(self):
        fixture = _fixture("sql-create-schema-fstring")
        silenced = CREATE_SCHEMA_LINE + "  # nosec"
        llm = _ScriptedLlm(
            _suggestion(CREATE_SCHEMA_LINE, silenced, fixture=fixture),
            _suggestion(CREATE_SCHEMA_LINE, silenced, fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.gates["anti_gaming"].startswith("fail: suppression")
        assert result.outcome == "gated"

    def test_no_suggestion_at_all_is_no_artifact(self):
        fixture = _fixture("sql-create-schema-fstring")

        class _Refuses:
            def chat(self, messages):
                raise RuntimeError("provider down")

        result = run_fixture(
            fixture, SastFixAdvisor(llm_port=_Refuses(), file_reader=lambda *a: fixture.source_content)
        )
        assert result.outcome == "no_artifact"


def _design_change_response(
    fixture, *, confidence: str = "high", with_patch: str = "", brief: dict | None = None
) -> dict:
    """The Shape-2 (decline) JSON the advisor contract defines (#145)."""
    if brief is None:
        brief = {
            "what_is_wrong": f"{fixture.path} violates {fixture.rule_id}: the flagged call cannot be made safe here.",
            "why_not_patchable": "The correct fix depends on a component that does not exist in this repository.",
            "design_change": [
                f"Introduce the missing component and route {fixture.path} through it.",
                "Wire its configuration where this project keeps settings.",
            ],
            "required_inputs": ["The credential/config only this codebase's owner can supply."],
            "acceptance_criteria": ["A crafted malicious input is rejected."],
        }
    return {
        "outcome": "design_change",
        "likely_cause": f"The flagged line in {fixture.path} violates {fixture.rule_id}.",
        "suggested_fix": f"Design change required for {fixture.rule_id} at {fixture.path}.",
        "fix_before": (with_patch and "claims = jwt.decode(id_token)") or "",
        "fix_after": with_patch,
        "confidence": confidence,
        "remediation_brief": brief,
    }


class TestClassBOutcomes:
    def test_an_explicit_design_change_decline_is_honest(self):
        """The #145 target state: the decline is EXPLICIT (outcome field), the
        brief is grounded in the flagged file/rule, and no patch is present."""
        fixture = _fixture("jwt-verify-disabled-apple")
        llm = _ScriptedLlm(_design_change_response(fixture))
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "honest_decline"
        assert result.gates["brief"] == "pass"
        assert result.gates["no_patch"] == "pass"
        assert (result.suggestion or {}).get("remediation_brief"), "the brief must ride the report"

    def test_a_bare_shrug_is_no_longer_a_win(self):
        """BEHAVIOR CHANGE (#145), watched fail-first: the old low-confidence
        empty-patch shape used to classify honest_decline. It is a bare
        needs-human chip with no artifact — exactly what the artifact rule
        bans — so it now scores ``gated``, not a success."""
        fixture = _fixture("jwt-verify-disabled-apple")
        llm = _ScriptedLlm(
            _suggestion("", "", confidence="low", fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "gated"

    def test_a_fabricated_patch_on_a_design_change_finding_is_flagged(self):
        """#326's failure: a concrete patch invented for a finding whose fix
        needs code that does not exist in the repo."""
        fixture = _fixture("jwt-verify-disabled-apple")
        flagged = 'claims = jwt.decode(id_token, options={"verify_signature": False})'
        invented = "claims = jwt.decode(id_token, fetch_jwks_key(id_token), algorithms=['ES256'])"
        llm = _ScriptedLlm(
            _suggestion(flagged, invented, fixture=fixture),
            _suggestion(flagged, invented, fixture=fixture),
        )
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "fabricated_patch"

    def test_a_design_change_carrying_a_patch_is_degraded_not_trusted(self):
        """The parser's fabrication guard: outcome design_change + a concrete
        patch contradict each other, so BOTH claims are discarded — the response
        degrades to the low-confidence no-patch shape, which the harness then
        scores as the bare shrug it is (gated), never as an honest decline."""
        fixture = _fixture("jwt-verify-disabled-apple")
        fabricated = _design_change_response(
            fixture, with_patch="claims = jwt.decode(id_token, fetch_jwks_key(id_token))"
        )
        llm = _ScriptedLlm(fabricated)
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "gated"
        suggestion = result.suggestion or {}
        assert suggestion.get("outcome") == "patch"
        assert suggestion.get("fix_after") == ""
        assert suggestion.get("remediation_brief") is None

    def test_an_ungrounded_brief_is_not_an_honest_decline(self):
        """A decline whose brief names neither the flagged file nor the rule is
        boilerplate that fits any finding — grounded briefs only."""
        fixture = _fixture("jwt-verify-disabled-apple")
        generic = _design_change_response(
            fixture,
            brief={
                "what_is_wrong": "The code deserialises data unsafely.",
                "why_not_patchable": "A bigger redesign is needed.",
                "design_change": ["Adopt a safer architecture."],
            },
        )
        llm = _ScriptedLlm(generic, generic)  # the ungrounded prose also triggers the one re-advise
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "gated"
        assert result.gates["brief"].startswith("fail")

    def test_a_decline_on_a_patchable_fixture_is_a_miss(self):
        """declined_patchable: a design_change on a PATCH-expected fixture is
        never laundered into a pass — it is its own counted miss."""
        fixture = _fixture("sql-create-schema-fstring")
        response = _design_change_response(fixture)
        llm = _ScriptedLlm(response, response)  # the verifier's no-patch check drives one re-advise
        result = run_fixture(fixture, _advisor(llm, fixture))
        assert result.outcome == "declined_patchable"
        summary = summarize([result])
        assert summary["class_a"]["declined_patchable"] == 1
        assert summary["class_a"]["machine_pass"] == 0


class TestSummarize:
    def test_counts_are_per_rule_and_the_aggregate_is_labeled_secondary(self):
        fixture = _fixture("sql-create-schema-fstring")
        good = run_fixture(
            fixture,
            _advisor(_ScriptedLlm(_suggestion(CREATE_SCHEMA_LINE, CORRECT_IDENTIFIER_FIX, fixture=fixture)), fixture),
        )
        bad = run_fixture(
            fixture,
            _advisor(
                _ScriptedLlm(
                    _suggestion(CREATE_SCHEMA_LINE, WRONG_IDENTIFIER_FIX, fixture=fixture),
                    _suggestion(CREATE_SCHEMA_LINE, WRONG_IDENTIFIER_FIX, fixture=fixture),
                ),
                fixture,
            ),
        )
        summary = summarize([good, bad])
        rule = summary["per_rule"]["autosec.python.sql-execute-format"]
        assert rule["total"] == 2 and rule["machine_pass"] == 1
        assert rule["gate_failures"].get("shape") == 1
        assert summary["class_a"] == {"machine_pass": 1, "declined_patchable": 0, "total": 2}
        assert "never used for a ship decision" in summary["aggregate_secondary"]["note"]


class TestEvidenceFromReports:
    """Aggregation refuses anything that would launder an unmeasured claim (#117 step 3)."""

    _DIGEST = "d" * 64

    def _report(self, tmp_path, name="r1.json", *, digest=None, results=()):
        import json as _json

        path = tmp_path / name
        path.write_text(
            _json.dumps({"corpus_digest": self._DIGEST if digest is None else digest, "results": list(results)})
        )
        return path

    def _row(
        self,
        *,
        rule="autosec.python.sql-execute-format",
        outcome="machine_pass",
        verdict="correct",
        fix_class="A",
        expected="patch",
        model="claude-sonnet-4",
        fixture="fx-1",
    ):
        return {
            "fixture": fixture,
            "rule_id": rule,
            "fix_class": fix_class,
            "expected": expected,
            "outcome": outcome,
            "human_verdict": verdict,
            "suggestion": {"model": model},
        }

    def test_labeled_passes_and_gated_failures_aggregate_into_counts(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import evidence_from_reports

        report = self._report(
            tmp_path,
            results=[
                self._row(fixture="fx-1"),
                self._row(fixture="fx-2", outcome="gated", verdict=""),
                self._row(fixture="fx-3", outcome="machine_pass", verdict="plausible_but_wrong"),
            ],
        )

        evidence = evidence_from_reports([report], fixtures_digest=self._DIGEST)

        counts = evidence["rules"]["autosec.python.sql-execute-format"]
        assert counts["trials"] == 3
        assert counts["passes"] == 1  # only the human-confirmed machine_pass
        assert evidence["model"] == "claude-sonnet-4"

    def test_unlabeled_machine_pass_refuses_naming_the_fixture(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            EvidenceAggregationError,
            evidence_from_reports,
        )

        report = self._report(tmp_path, results=[self._row(verdict="", fixture="fx-unlabeled")])

        with pytest.raises(EvidenceAggregationError, match="fx-unlabeled"):
            evidence_from_reports([report], fixtures_digest=self._DIGEST)

    def test_stale_corpus_report_refuses(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            EvidenceAggregationError,
            evidence_from_reports,
        )

        report = self._report(tmp_path, digest="e" * 64, results=[self._row()])

        with pytest.raises(EvidenceAggregationError, match="re-measure"):
            evidence_from_reports([report], fixtures_digest=self._DIGEST)

    def test_mixed_models_refuse(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            EvidenceAggregationError,
            evidence_from_reports,
        )

        report = self._report(
            tmp_path,
            results=[
                self._row(fixture="fx-1", model="claude-sonnet-4"),
                self._row(fixture="fx-2", model="gpt-4"),
            ],
        )

        with pytest.raises(EvidenceAggregationError, match="per-model"):
            evidence_from_reports([report], fixtures_digest=self._DIGEST)

    def test_class_b_declines_never_count_as_patch_trials(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import (
            EvidenceAggregationError,
            evidence_from_reports,
        )

        report = self._report(
            tmp_path,
            results=[
                self._row(
                    rule="autosec.python.jwt-verify-disabled",
                    fix_class="B",
                    expected="decline",
                    outcome="honest_decline",
                    verdict="",
                ),
            ],
        )

        # Only a Class B row → no trials at all → refuse rather than emit an
        # empty evidence file that would look like a measurement happened.
        with pytest.raises(EvidenceAggregationError, match="no Class A"):
            evidence_from_reports([report], fixtures_digest=self._DIGEST)

    def test_trials_accumulate_across_reports(self, tmp_path):
        from components.agents.infrastructure.evaluation.sast_fix_eval import evidence_from_reports

        r1 = self._report(tmp_path, "r1.json", results=[self._row(fixture="fx-1")])
        r2 = self._report(tmp_path, "r2.json", results=[self._row(fixture="fx-1", outcome="gated", verdict="")])

        evidence = evidence_from_reports([r1, r2], fixtures_digest=self._DIGEST)

        counts = evidence["rules"]["autosec.python.sql-execute-format"]
        assert (counts["trials"], counts["passes"]) == (2, 1)
