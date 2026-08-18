"""The advisor's explicit decline (task #145) — parser contract + brief entity.

The measured motivation: with only the patch shape available, BOTH Class B
evidence fixtures fabricated concrete patches in all 10 passes (0/20 honest
declines). These tests pin the new contract: the parser accepts the
``design_change`` shape, enforces its exclusivity (a decline carrying a patch is
a fabrication and is degraded, never trusted), and the grounding gate does not
force a confident decline down to low confidence.

Zero LLM, zero network — the parser and the domain entity are pure functions.
"""

from __future__ import annotations

import json

import pytest

from components.code_security.application.sast_fix_advisor_service import _SYSTEM, SastFixAdvisor
from components.code_security.domain.remediation_brief import RemediationBrief
from components.shared_kernel.domain.triage import OUTCOME_DESIGN_CHANGE, OUTCOME_PATCH

pytestmark = pytest.mark.unit


_BRIEF = {
    "what_is_wrong": "auth/jwt_apple_auth.py decodes Apple id_tokens with verify_signature disabled.",
    "why_not_patchable": "Verification needs the issuer's real public key; no key source exists in this repo.",
    "design_change": [
        "Fetch and cache Apple's JWKS, select the key by the token's kid header.",
        "Verify with a pinned algorithm list plus audience and issuer checks.",
    ],
    "required_inputs": ["The Apple client id used as the token audience."],
    "acceptance_criteria": ["A token with a tampered payload is rejected."],
}


def _design_change_json(**overrides) -> str:
    data = {
        "outcome": "design_change",
        "likely_cause": "jwt.decode runs with signature verification disabled.",
        "suggested_fix": "Design change: verify id_tokens in auth/jwt_apple_auth.py against Apple's JWKS keys.",
        "fix_before": "",
        "fix_after": "",
        "confidence": "high",
        "remediation_brief": _BRIEF,
    }
    data.update(overrides)
    return json.dumps(data)


class TestParserAcceptsBothShapes:
    def test_design_change_shape_parses_with_the_brief(self):
        suggestion = SastFixAdvisor._parse(_design_change_json())
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_DESIGN_CHANGE
        assert suggestion.confidence == "high"  # a confident decline stays confident
        assert suggestion.fix_before == "" and suggestion.fix_after == ""
        assert suggestion.remediation_brief is not None
        assert suggestion.remediation_brief.design_change == tuple(_BRIEF["design_change"])

    def test_patch_shape_without_an_outcome_field_stays_the_patch_contract(self):
        """Back-compat: a model (or a cached row) that never learned the outcome
        field behaves exactly as before."""
        suggestion = SastFixAdvisor._parse(
            json.dumps(
                {
                    "likely_cause": "Raw SQL built with %-formatting.",
                    "suggested_fix": "Use sql.Identifier in migrate_schema.py.",
                    "fix_before": 'cursor.execute("DROP TABLE %s" % table)',
                    "fix_after": 'cursor.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(table)))',
                    "confidence": "high",
                }
            )
        )
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_PATCH
        assert suggestion.remediation_brief is None
        assert suggestion.fix_after.startswith("cursor.execute(sql.SQL")

    def test_as_dict_carries_outcome_and_brief(self):
        suggestion = SastFixAdvisor._parse(_design_change_json())
        data = suggestion.as_dict()
        assert data["outcome"] == OUTCOME_DESIGN_CHANGE
        assert data["remediation_brief"]["what_is_wrong"] == _BRIEF["what_is_wrong"]


class TestFabricationIsInvalid:
    """A design_change carrying a patch contradicts itself — the #326 fabrication
    wearing a new label. Both claims are discarded; the response degrades to the
    old honest low-confidence no-patch shape (prose kept, nothing trusted)."""

    def test_design_change_with_a_fix_after_is_degraded(self):
        suggestion = SastFixAdvisor._parse(
            _design_change_json(fix_after="claims = jwt.decode(id_token, fetch_jwks_key(id_token))")
        )
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_PATCH
        assert suggestion.confidence == "low"
        assert suggestion.fix_before == "" and suggestion.fix_after == ""
        assert suggestion.remediation_brief is None

    def test_design_change_with_a_fix_before_is_degraded(self):
        suggestion = SastFixAdvisor._parse(_design_change_json(fix_before="claims = jwt.decode(id_token)"))
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_PATCH
        assert suggestion.remediation_brief is None

    def test_design_change_without_a_brief_is_degraded(self):
        """An outcome stamp with nothing behind it is a bare needs-human chip —
        not an artifact. Degraded, and the prose kept."""
        suggestion = SastFixAdvisor._parse(_design_change_json(remediation_brief=None))
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_PATCH
        assert suggestion.confidence == "low"

    def test_design_change_with_a_hollow_brief_is_degraded(self):
        suggestion = SastFixAdvisor._parse(
            _design_change_json(remediation_brief={"what_is_wrong": "x", "design_change": []})
        )
        assert suggestion is not None
        assert suggestion.outcome == OUTCOME_PATCH
        assert suggestion.remediation_brief is None


class TestGroundingGate:
    def test_a_confident_decline_passes_the_grounding_gate(self):
        """The empty-fix_before rule ("pass only at low confidence") is a patch
        rule; a design_change decline has no patch BY CONTRACT and must not be
        discarded for being confident."""
        suggestion = SastFixAdvisor._parse(_design_change_json(confidence="high"))
        assert SastFixAdvisor._is_grounded(suggestion, window="anything", snippet="jwt.decode(...)") is True

    def test_the_patch_shape_rules_are_unchanged(self):
        shrug = SastFixAdvisor._parse(
            json.dumps(
                {
                    "likely_cause": "c",
                    "suggested_fix": "f",
                    "fix_before": "",
                    "fix_after": "",
                    "confidence": "high",
                }
            )
        )
        assert SastFixAdvisor._is_grounded(shrug, window="w", snippet="s") is False  # confident shrug, no patch


class TestSystemPromptContract:
    def test_the_system_prompt_defines_both_shapes(self):
        assert '"outcome": "patch"' in _SYSTEM
        assert '"outcome": "design_change"' in _SYSTEM
        assert "remediation_brief" in _SYSTEM

    def test_the_system_prompt_forbids_patch_code_on_a_decline(self):
        assert "MUST NOT contain any code in fix_before/fix_after" in _SYSTEM


class TestRemediationBriefEntity:
    def test_from_raw_requires_the_load_bearing_fields(self):
        assert RemediationBrief.from_raw(_BRIEF) is not None
        assert RemediationBrief.from_raw(None) is None
        assert RemediationBrief.from_raw("prose") is None
        assert RemediationBrief.from_raw({**_BRIEF, "what_is_wrong": " "}) is None
        assert RemediationBrief.from_raw({**_BRIEF, "why_not_patchable": ""}) is None
        assert RemediationBrief.from_raw({**_BRIEF, "design_change": []}) is None

    def test_optional_sections_may_be_absent(self):
        brief = RemediationBrief.from_raw(
            {k: v for k, v in _BRIEF.items() if k not in ("required_inputs", "acceptance_criteria")}
        )
        assert brief is not None
        assert brief.required_inputs == () and brief.acceptance_criteria == ()

    def test_render_markdown_is_legible_and_code_free(self):
        brief = RemediationBrief.from_raw(_BRIEF)
        text = brief.render_markdown()
        assert "**What's wrong:**" in text
        assert "**Why a local edit can't fix it:**" in text
        assert "1. Fetch and cache Apple's JWKS" in text
        assert "**What you need to supply:**" in text
        assert "**How you'll know it's fixed:**" in text
        assert "```" not in text

    def test_as_text_flattens_every_field_for_the_grounding_check(self):
        text = RemediationBrief.from_raw(_BRIEF).as_text()
        for value in (_BRIEF["what_is_wrong"], _BRIEF["why_not_patchable"], *_BRIEF["design_change"]):
            assert value in text
