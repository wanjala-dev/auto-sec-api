"""The graded snippet is replayed exactly, or not at all (ADR 0025 Phase 2).

These are mostly NEGATIVE tests, and deliberately so. The happy path — snippet
found once, applied — is the easy half. The half that matters is everything this
must REFUSE: a snippet that appears three times, a file that drifted since
triage, an empty "no confident fix". Each of those, applied optimistically,
would commit a wrong edit to a customer's repository under a PR body that says
the fix was validated. Returning ``None`` hands the case to the fallback advisor
and costs nothing; guessing costs trust.
"""

import pytest

from components.integrations.application.verified_patch_service import build_verified_proposal
from components.shared_kernel.domain.patch_attestation import (
    PATCH_ATTESTATION_KEY,
    RESULT_FAILED,
    RESULT_PASSED,
    build_attestation,
)

pytestmark = pytest.mark.unit


_FILE = """import jwt


def verify(token):
    payload = jwt.decode(token, options={"verify_signature": False})
    return payload
"""


def _payload(**over):
    """A card as the specialist leaves it: snippet PLUS the attestation proving a
    grader passed that exact snippet. Fixtures mint the stamp last, over whatever
    overrides were applied, so the digest always binds to the snippet under test —
    tests that want an UNBACKED snippet must strip it explicitly (below)."""
    base = {
        "fix_before": '    payload = jwt.decode(token, options={"verify_signature": False})',
        "fix_after": '    payload = jwt.decode(token, key, algorithms=["RS256"])',
        "start_line": 5,
        "suggested_fix": "Verify the signature.",
    }
    base.update(over)
    base[PATCH_ATTESTATION_KEY] = build_attestation(
        verifier="code_security_agent",
        fix_before=str(base.get("fix_before") or ""),
        fix_after=str(base.get("fix_after") or ""),
        result=RESULT_PASSED,
        verified_at="2026-08-12T00:00:00+00:00",
    )
    return base


class TestReplaysTheGradedFix:
    def test_applies_the_snippet_and_leaves_the_rest_untouched(self):
        proposal = build_verified_proposal(payload=_payload(), path="auth.py", current_content=_FILE)

        assert proposal is not None
        assert 'algorithms=["RS256"]' in proposal.updated_content
        assert "verify_signature" not in proposal.updated_content
        # Everything around the fix survives byte-for-byte.
        assert proposal.updated_content.startswith("import jwt\n")
        assert proposal.updated_content.endswith("    return payload\n")
        assert proposal.path == "auth.py"

    def test_carries_the_agents_own_summary(self):
        proposal = build_verified_proposal(payload=_payload(), path="auth.py", current_content=_FILE)

        assert proposal.change_summary == "Verify the signature."

    def test_matches_when_the_card_lost_the_indentation(self):
        # The snippet on the card is frequently dedented. The match must survive
        # that, and the replacement must be re-indented to the block it replaces —
        # in Python, getting this wrong changes the program, not its formatting.
        payload = _payload(
            fix_before='payload = jwt.decode(token, options={"verify_signature": False})',
            fix_after='payload = jwt.decode(token, key, algorithms=["RS256"])',
        )

        proposal = build_verified_proposal(payload=payload, path="auth.py", current_content=_FILE)

        assert proposal is not None
        assert '    payload = jwt.decode(token, key, algorithms=["RS256"])\n' in proposal.updated_content

    def test_replays_a_multi_line_snippet(self):
        payload = _payload(
            fix_before='    payload = jwt.decode(token, options={"verify_signature": False})\n    return payload',
            fix_after='    payload = jwt.decode(token, key, algorithms=["RS256"])\n    return payload',
        )

        proposal = build_verified_proposal(payload=payload, path="auth.py", current_content=_FILE)

        assert proposal is not None
        assert proposal.updated_content.count("return payload") == 1


class TestRefusesRatherThanGuesses:
    def test_no_snippet_returns_none(self):
        assert (
            build_verified_proposal(payload=_payload(fix_before="", fix_after=""), path="a.py", current_content=_FILE)
            is None
        )

    def test_fix_after_alone_returns_none(self):
        # An "after" with no "before" names no location. Nothing to replay.
        assert build_verified_proposal(payload=_payload(fix_before=""), path="a.py", current_content=_FILE) is None

    def test_drifted_file_returns_none(self):
        # The card was triaged against a version of the file that no longer
        # exists. This is the case an optimistic matcher gets wrong.
        moved_on = _FILE.replace("verify_signature", "verify_exp")

        assert build_verified_proposal(payload=_payload(), path="a.py", current_content=moved_on) is None

    def test_ambiguous_snippet_far_from_the_finding_returns_none(self):
        repeated = (
            "def a(token):\n"
            '    payload = jwt.decode(token, options={"verify_signature": False})\n'
            "    return payload\n"
            "\n\n" + ("# filler\n" * 200) + "def b(token):\n"
            '    payload = jwt.decode(token, options={"verify_signature": False})\n'
            "    return payload\n"
        )

        # start_line=0 — no anchor to disambiguate with, two candidates.
        assert build_verified_proposal(payload=_payload(start_line=0), path="a.py", current_content=repeated) is None

    def test_ambiguous_snippet_is_resolved_by_the_findings_line(self):
        # Same duplicated idiom, but the finding names WHICH one. The far copy is
        # outside the anchor window, so exactly one candidate qualifies.
        repeated = (
            "def a(token):\n"
            '    payload = jwt.decode(token, options={"verify_signature": False})\n'
            "    return payload\n"
            "\n\n" + ("# filler\n" * 200) + "def b(token):\n"
            '    payload = jwt.decode(token, options={"verify_signature": False})\n'
            "    return payload\n"
        )

        proposal = build_verified_proposal(payload=_payload(start_line=2), path="a.py", current_content=repeated)

        assert proposal is not None
        # The FIRST occurrence was fixed; the far one is untouched.
        assert proposal.updated_content.count("verify_signature") == 1
        assert proposal.updated_content.splitlines()[1].strip().startswith("payload = jwt.decode(token, key")

    def test_blank_snippet_never_matches_everywhere(self):
        assert (
            build_verified_proposal(
                payload=_payload(fix_before="\n\n", fix_after="x = 1"), path="a.py", current_content=_FILE
            )
            is None
        )

    def test_noop_fix_returns_none(self):
        before = '    payload = jwt.decode(token, options={"verify_signature": False})'

        assert (
            build_verified_proposal(
                payload=_payload(fix_before=before, fix_after=before), path="a.py", current_content=_FILE
            )
            is None
        )

    def test_crlf_file_still_matches(self):
        crlf = _FILE.replace("\n", "\r\n")

        assert build_verified_proposal(payload=_payload(), path="a.py", current_content=crlf) is not None


class TestReplayRequiresProofThatAGraderPassedIt:
    """The defect this class exists for, found by measuring against real cards.

    Phase 2a treated "the card has a snippet" as "the snippet was graded". Every
    card triaged before the grading existed carries a snippet no oracle ever saw —
    including, live on our own board, the exact
    ``cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))`` that ADR 0025
    records as semantically wrong. Replaying one shipped known-wrong code to a
    customer's repository under a PR body asserting it had been validated.

    Absence of proof must never resolve to "verified" (fail-closed; SLSA VSA binds
    a verdict to a subject digest for exactly this reason).
    """

    def test_a_snippet_with_no_attestation_is_not_replayed(self):
        payload = _payload()
        payload.pop(PATCH_ATTESTATION_KEY)

        assert build_verified_proposal(payload=payload, path="a.py", current_content=_FILE) is None

    def test_the_real_stale_card_shape_is_refused(self):
        """Modelled on live card 9976: a pre-grading snippet, high confidence, no
        attestation. Before this fix it replayed and shipped as verified."""
        stale = {
            "fix_before": '    payload = jwt.decode(token, options={"verify_signature": False})',
            "fix_after": '    payload = jwt.decode(token, key, algorithms=["RS256"])',
            "start_line": 5,
            "confidence": "high",
        }

        assert build_verified_proposal(payload=stale, path="a.py", current_content=_FILE) is None

    def test_an_edited_snippet_loses_its_attestation(self):
        """The digest binding, which is what makes this more than a staleness check.
        Finding payloads are operator-editable in the HUD: without binding the
        verdict to the bytes, someone could change ``fix_after`` after grading and
        the engine would still commit it wearing the original's verdict."""
        payload = _payload()
        payload["fix_after"] = "    payload = jwt.decode(token, verify=False)  # tampered"

        assert build_verified_proposal(payload=payload, path="a.py", current_content=_FILE) is None

    def test_a_failed_verdict_is_not_a_licence_to_ship(self):
        payload = _payload()
        payload[PATCH_ATTESTATION_KEY] = build_attestation(
            verifier="code_security_agent",
            fix_before=str(payload["fix_before"]),
            fix_after=str(payload["fix_after"]),
            result=RESULT_FAILED,
            verified_at="2026-08-12T00:00:00+00:00",
        )

        assert build_verified_proposal(payload=payload, path="a.py", current_content=_FILE) is None

    def test_a_verdict_from_a_superseded_policy_is_not_a_verdict(self):
        payload = _payload()
        payload[PATCH_ATTESTATION_KEY] = {**payload[PATCH_ATTESTATION_KEY], "policy_version": "2020-01-01.ancient"}

        assert build_verified_proposal(payload=payload, path="a.py", current_content=_FILE) is None

    def test_a_malformed_attestation_is_no_attestation(self):
        for junk in ("passed", {"result": "passed"}, {}, None, 42):
            payload = _payload()
            payload[PATCH_ATTESTATION_KEY] = junk

            assert build_verified_proposal(payload=payload, path="a.py", current_content=_FILE) is None, junk
