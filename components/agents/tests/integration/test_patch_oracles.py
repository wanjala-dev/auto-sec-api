"""The patch oracles: validate the fix, stop coaxing the model (ADR 0025).

Measured on 319 LLM security patches (arXiv 2603.10072): 24.8% fully correct,
51.4% "semantic misunderstanding" — syntactically valid code applying a
fundamentally wrong repair strategy — and, decisively, a BIMODAL outcome
distribution with only 0.3% landing near-correct. That last number is why this
file exists instead of a third round of prompt tuning: there is no near-miss band
for a better instruction to close. What separates a shippable patch from a
plausible one is validation, not persuasion.

Three deterministic oracles run before a patch is called verified, cheapest first:

  L0  is there a patch at all      — guidance is not an artifact
  L1  does it still parse          — 13.2% of LLM security patches do not compile
  L3  does it reproduce a known-wrong shape for its rule class

L2 (re-scan the patched content with the same rule) needs the opengrep scan-Job
substrate and is deliberately not faked here — see the ADR.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import verify_suggestion
from components.code_security.domain.remediation_guidance import (
    STRATEGY_GUIDANCE_ONLY,
    guidance_for,
    patch_is_attempted,
    patch_parses,
)

pytestmark = pytest.mark.unit

_SOURCE = "ai.code_security"
_PAYLOAD = {
    "rule_id": "autosec.python.sql-execute-format",
    "path": "api/scripts/migrate_schema.py",
    "snippet": 'cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")',
    "language": "python",
}
_GOOD_PROSE = "Compose the identifier with sql.Identifier in migrate_schema.py rather than binding it."
_GOOD_PATCH = 'cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))'


class TestL0GuidanceIsNotAnArtifact:
    """Three live findings shipped `verified` with no patch at all."""

    def test_empty_patch_from_a_patchable_class_is_not_verified(self):
        result = verify_suggestion(source_type=_SOURCE, payload=_PAYLOAD, suggestion_text=_GOOD_PROSE, patch_code="")
        assert result.grounded is False
        assert "no patch" in result.reason.lower()

    def test_a_caller_with_no_patch_to_grade_is_unaffected(self):
        """``None`` means "I have no patch", not "the advisor returned none"."""
        result = verify_suggestion(source_type=_SOURCE, payload=_PAYLOAD, suggestion_text=_GOOD_PROSE)
        assert result.grounded is True

    def test_guidance_only_classes_may_ship_prose_alone(self):
        """For a class we deliberately do not patch, prose IS the artifact."""
        jwt = guidance_for("autosec.python.jwt-verify-disabled")
        assert jwt.strategy == STRATEGY_GUIDANCE_ONLY
        assert patch_is_attempted(jwt) is False
        result = verify_suggestion(
            source_type=_SOURCE,
            payload={
                "rule_id": "autosec.python.jwt-verify-disabled",
                "path": "components/identity/adapters/apple_auth.py",
                "snippet": "decoded = jwt.decode(id_token, '', verify=False)",
                "language": "python",
            },
            suggestion_text=(
                "Verify the token in apple_auth.py against the issuer's published key with a pinned "
                "algorithm list — jwt.decode must not run with verification off."
            ),
            patch_code="",
        )
        assert result.grounded is True

    def test_an_unmapped_rule_still_expects_a_patch(self):
        """Degrade to today's behaviour, never silently drop the artifact."""
        assert patch_is_attempted(None) is True


class TestL1ItMustStillParse:
    def test_a_patch_that_breaks_the_syntax_is_rejected(self):
        broken = 'cursor.execute(sql.SQL("CREATE SCHEMA {}".format(sql.Identifier(schema)))'  # unbalanced
        result = verify_suggestion(
            source_type=_SOURCE, payload=_PAYLOAD, suggestion_text=_GOOD_PROSE, patch_code=broken
        )
        assert result.grounded is False
        assert "syntax" in result.reason.lower() or "parse" in result.reason.lower()

    def test_a_valid_patch_passes(self):
        result = verify_suggestion(
            source_type=_SOURCE, payload=_PAYLOAD, suggestion_text=_GOOD_PROSE, patch_code=_GOOD_PATCH
        )
        assert result.grounded is True

    def test_an_indented_fragment_is_not_mistaken_for_broken_code(self):
        """The costly false positive: a body line does not parse standalone."""
        verdict = patch_parses(
            patch_code="        cursor.execute('SELECT 1')",
            before_code="        cursor.execute('SELECT 2')",
            language="python",
        )
        assert verdict.ok is True

    def test_inconclusive_when_neither_side_parses(self):
        """If the code being replaced does not parse alone either, we cannot tell."""
        verdict = patch_parses(patch_code="else:", before_code="if x:", language="python")
        assert verdict.ok is True

    def test_non_python_is_not_judged_by_the_python_parser(self):
        verdict = patch_parses(patch_code="const x = () => {};", before_code="var x = 1;", language="javascript")
        assert verdict.ok is True


class TestGroundingCannotBeSatisfiedByEcho:
    """A live suggestion read, in full: "Apply rule <id> to file <name>"."""

    def test_echoing_the_rule_and_file_is_not_engagement(self):
        result = verify_suggestion(
            source_type=_SOURCE,
            payload=_PAYLOAD,
            suggestion_text="Apply rule autosec.python.sql-execute-format to file migrate_schema.py",
            patch_code=_GOOD_PATCH,
        )
        assert result.grounded is False
        assert "echoes" in result.reason.lower()

    def test_a_substantive_suggestion_still_passes(self):
        result = verify_suggestion(
            source_type=_SOURCE, payload=_PAYLOAD, suggestion_text=_GOOD_PROSE, patch_code=_GOOD_PATCH
        )
        assert result.grounded is True


class TestOracleOrder:
    """Cheapest first, and the most specific reason wins — the reason becomes the
    re-advise feedback, so a vague one wastes the single retry."""

    def test_a_wrong_shape_is_named_as_a_shape_problem_not_a_grounding_one(self):
        result = verify_suggestion(
            source_type=_SOURCE,
            payload=_PAYLOAD,
            suggestion_text=_GOOD_PROSE,
            patch_code='cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))',
        )
        assert result.grounded is False
        assert "known-wrong shape" in result.reason
