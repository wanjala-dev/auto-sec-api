"""Proof that THIS patch was graded — bound to the patch itself.

The cross-context contract for "has this fix actually been through the grading
pass?" (ADR 0025 Phase 2c). Written by ``agents`` when the oracles and the rubric
run; read by ``integrations`` before the draft-PR engine replays a snippet. It
lives in the shared kernel because both contexts depend on the CONTRACT and
neither may depend on the other (C1/C4).

## Why this exists

Phase 2a taught the engine to ship the ``fix_before`` -> ``fix_after`` from the
card instead of asking an advisor for a fresh rewrite, on the reasoning that the
card's snippet is the rubric-graded one. That reasoning has a hole, found by
measuring against real cards rather than constructed ones: **the presence of a
snippet is not evidence that a grader ever saw it.**

Every card triaged before the grading existed carries a snippet produced with no
oracles and no rubric. Replaying one shipped a known-wrong patch — the exact
``cursor.execute("CREATE SCHEMA IF NOT EXISTS %s", (schema,))`` that ADR 0025
records as semantically wrong — under a PR body asserting it had been validated.
A verification claim that floats free of the artifact it describes is worse than
no claim, because it is trusted.

## The shape, and where it comes from

Modelled on SLSA's **Verification Summary Attestation**, which solves exactly
this: how a consumer knows an artifact was verified, by whom, against what,
without redoing the work. The load-bearing field there is ``subject.digest`` —
the attestation binds to a specific artifact hash, so it cannot be inherited by
different content. ``subject_digest`` below is that field.

The SLSA spec deliberately leaves staleness and missing-attestation policy to the
consumer, so ours is stated here rather than left implicit in a call site:

* **No attestation → ungraded.** Absence of proof never resolves to "verified"
  (fail-closed; NIST SP 800-207 "never trust, always verify"). The specialist
  re-runs and produces a genuinely graded snippet.
* **Digest mismatch → ungraded.** The attestation describes different bytes than
  the card now carries. This is not only staleness: finding payloads are
  operator-editable in the HUD, so without the binding an edited ``fix_after``
  would inherit the original's verdict.
* **Different policy version → ungraded.** A snippet graded by a rubric or oracle
  set we have since changed was graded against a standard that no longer holds.

References: SLSA VSA (https://slsa.dev/spec/v0.1/verification_summary),
in-toto attestation (https://github.com/in-toto/attestation).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: Bump when the grading standard changes in a way that invalidates earlier
#: verdicts — a new/removed oracle, or a materially rewritten rubric. Existing
#: attestations then read as ungraded and their findings re-run, which is the
#: intended cost: a verdict from a superseded standard is not a verdict.
PATCH_POLICY_VERSION = "2026-08-12.oracles-v1+rubric-v1"

#: Payload key the attestation is stamped under, on the finding's payload dict.
PATCH_ATTESTATION_KEY = "patch_attestation"

RESULT_PASSED = "passed"
RESULT_FAILED = "failed"


def patch_digest(fix_before: str, fix_after: str) -> str:
    """A stable content hash of the graded patch — the attestation's subject.

    Both halves are covered: ``fix_before`` locates the edit and ``fix_after`` is
    the replacement, so a change to either produces a different patch and must
    invalidate the verdict. Whitespace is NOT normalised — in Python indentation
    is semantics, and two snippets differing only in leading whitespace are
    genuinely different patches.
    """
    payload = f"{fix_before or ''}\x00{fix_after or ''}".encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PatchAttestation:
    """A verifier's statement about one specific patch."""

    #: WHO graded it — the verifier's identity (SLSA ``verifier.id``).
    verifier: str
    #: WHAT standard was applied (SLSA ``policy``), as :data:`PATCH_POLICY_VERSION`.
    policy_version: str
    #: WHICH bytes were graded (SLSA ``subject.digest``) — the binding that makes
    #: the claim unable to travel to different content.
    subject_digest: str
    #: The verdict (SLSA ``verificationResult``).
    result: str
    #: When (SLSA ``timeVerified``), ISO-8601.
    verified_at: str

    def as_dict(self) -> dict:
        return {
            "verifier": self.verifier,
            "policy_version": self.policy_version,
            "subject_digest": self.subject_digest,
            "result": self.result,
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> PatchAttestation | None:
        """Parse a stamp off a payload. Anything malformed is NO attestation —
        a half-readable claim must not be a partly-trusted one."""
        if not isinstance(raw, dict):
            return None
        try:
            attestation = cls(
                verifier=str(raw["verifier"]),
                policy_version=str(raw["policy_version"]),
                subject_digest=str(raw["subject_digest"]),
                result=str(raw["result"]),
                verified_at=str(raw.get("verified_at") or ""),
            )
        except (KeyError, TypeError):
            return None
        return attestation if attestation.subject_digest else None


def build_attestation(*, verifier: str, fix_before: str, fix_after: str, result: str, verified_at: str) -> dict:
    """Stamp a verdict onto the patch that was actually graded."""
    return PatchAttestation(
        verifier=verifier,
        policy_version=PATCH_POLICY_VERSION,
        subject_digest=patch_digest(fix_before, fix_after),
        result=result,
        verified_at=verified_at,
    ).as_dict()


def is_graded(payload: dict) -> bool:
    """Does this finding carry a PASSED attestation covering the snippet it holds?

    The single question both the re-run gate and the draft-PR replay ask. Every
    "no" path — absent, malformed, failed, superseded policy, or describing
    different bytes — returns False, so the caller falls back to a genuinely
    graded pass rather than trusting an unbacked claim.
    """
    if not isinstance(payload, dict):
        return False
    attestation = PatchAttestation.from_dict(payload.get(PATCH_ATTESTATION_KEY))
    if attestation is None or attestation.result != RESULT_PASSED:
        return False
    if attestation.policy_version != PATCH_POLICY_VERSION:
        return False
    expected = patch_digest(str(payload.get("fix_before") or ""), str(payload.get("fix_after") or ""))
    return attestation.subject_digest == expected
