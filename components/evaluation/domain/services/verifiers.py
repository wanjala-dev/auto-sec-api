"""The deterministic half of the axis grading (ADR 0033 D2).

Two of the five triage axes are mechanical, so they are answered here rather
than by the LLM judge: ``fix_applies`` and ``no_fabricated_asset``. Everything
in this module is a pure function over its arguments — no I/O, no Django, no
clock, no network. That is what makes these axes free to grade, stable across
re-runs, and exempt from D6's judge-agreement machinery entirely.

Three properties are deliberate and each is asserted by a test.

**A result carries a REASON, not just a boolean.** ``False`` is rendered to an
operator who is trying to work out what their agent did wrong; a bare False
sends them to the raw output to re-derive it. The reason names the specific
path or URN that failed, because "the patch was invalid" is the same non-answer
in a different font.

**Every function is TOTAL.** Malformed input — ``None``, bytes, a dict where a
string was expected, a truncated diff — returns a failed or unmeasured result,
never an exception. These run inside a loop over every case in a run; one
malformed agent output must degrade one case, not abort the run and lose the
other forty-nine results with it.

**Unverifiable is NOT failed.** Hence the three-valued outcome. If nobody
supplied an asset inventory, we cannot tell a fabricated URN from a real one,
and reporting that as a fabrication would be a false accusation against the
customer's agent. ADR 0032's honesty rule applies unchanged: a check with no
observation reads NOT MEASURED, never as a failure and never as clean. It maps
onto persistence directly — ``EvalCaseResult.axis_verdicts`` simply omits the
axis, which the model's own docstring already defines as not-measured.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

#: Both schemes ``shared_kernel.domain.security.AssetUrn`` can produce: a raw
#: AWS ARN used verbatim, or the namespaced ``urn:<source_system>:<ref>`` form.
#: Anything else is not treated as an asset reference at all — see
#: ``_extract_asset_references`` for why that bias is the safe one.
_ASSET_REFERENCE = re.compile(r"\b(?:arn|urn):[a-z0-9][a-z0-9._\-]*:[^\s\"'<>`|]+", re.IGNORECASE)

#: ``@@ -old[,count] +new[,count] @@`` — the unified-diff hunk header.
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")

_DEV_NULL = "/dev/null"

#: Trailing characters a URN picks up from prose ("... in arn:aws:s3:::logs.").
_TRAILING_PUNCTUATION = ".,;:!?)]}>\"'`"


class Outcome(Enum):
    """Three states, because "we could not check" is not "it failed"."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_MEASURED = "not_measured"


@dataclass(frozen=True)
class VerificationResult:
    """One axis's deterministic verdict, with the reason an operator will read."""

    axis: str
    outcome: Outcome
    reason: str
    #: The specific paths or URNs behind the verdict. Kept structured as well as
    #: interpolated into ``reason`` so a UI can link them without re-parsing prose.
    evidence: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """True only on a positive verdict — NOT_MEASURED is not a pass."""
        return self.outcome is Outcome.PASSED

    @property
    def failed(self) -> bool:
        """True only on a negative verdict — NOT_MEASURED is not a failure."""
        return self.outcome is Outcome.FAILED

    @property
    def measured(self) -> bool:
        return self.outcome is not Outcome.NOT_MEASURED

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "outcome": self.outcome.value,
            "passed": self.passed,
            "measured": self.measured,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


# ── input coercion ───────────────────────────────────────────────────────────
# Totality is implemented by narrowing types up front rather than by wrapping
# the body in `except Exception`. A blanket except would also swallow a genuine
# bug in the verifier itself and report it to the customer as a failing agent.


def _as_text(value: object) -> str | None:
    """Return ``value`` as text, or ``None`` if it is not text-like."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return None


def _as_string_set(value: object) -> tuple[str, ...] | None:
    """Return a tuple of the strings in ``value``, or ``None`` if unusable.

    A bare string is treated as a one-element collection: callers pass a path
    or a URN, and silently iterating it character-by-character would produce a
    verdict from nonsense.
    """
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray)):
        single = _as_text(value)
        return (single,) if single else ()
    if isinstance(value, Iterable):
        items = []
        for item in value:
            text = _as_text(item)
            if text and text.strip():
                items.append(text.strip())
        return tuple(items)
    return None


# ── fix_applies ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _PatchTarget:
    path: str
    creates_file: bool


def _normalise_path(raw: str) -> str:
    """Strip the decorations a diff puts around a path, keeping the path."""
    path = raw.split("\t", 1)[0].strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _path_candidates(raw: str) -> tuple[str, ...]:
    """The forms a target path could legitimately take in the file inventory.

    ``git diff`` writes ``a/`` and ``b/`` prefixes; a plain ``diff -u`` does
    not. Rather than guess which tool produced the patch, both readings are
    offered and a match on either counts — guessing wrong here would fail a
    correct patch, and a false failure is the expensive direction.
    """
    normalised = _normalise_path(raw)
    candidates = [normalised]
    for prefix in ("a/", "b/"):
        if normalised.startswith(prefix):
            candidates.append(normalised[len(prefix) :])
    return tuple(candidates)


def _display_path(raw: str) -> str:
    """The path as a human would write it — without the diff's ``a/``/``b/``.

    Reported rather than the raw header text because the reason string is read
    by an operator checking whether the file really is missing, and
    ``b/src/thing.py`` sends them looking for a directory called ``b``.
    """
    return _path_candidates(raw)[-1]


def _parse_unified_diff(patch: str) -> tuple[list[_PatchTarget], int, list[str]]:
    """Return (targets, well-formed hunk count, malformed hunk headers)."""
    targets: list[_PatchTarget] = []
    hunks = 0
    malformed: list[str] = []
    pending_old: str | None = None

    for line in patch.splitlines():
        if line.startswith("--- "):
            pending_old = line[4:]
        elif line.startswith("+++ "):
            new_raw = line[4:]
            old_path = _normalise_path(pending_old) if pending_old is not None else ""
            new_path = _normalise_path(new_raw)
            pending_old = None
            if new_path.lstrip("/") == _DEV_NULL.lstrip("/"):
                # Deletion: the file that must exist is the OLD side.
                targets.append(_PatchTarget(path=old_path, creates_file=False))
            else:
                # A `--- /dev/null` old side means the patch CREATES this file,
                # so the path is not expected in the inventory. Requiring it
                # would fail every legitimate "add a policy file" remediation.
                creates = old_path.lstrip("/") == _DEV_NULL.lstrip("/")
                targets.append(_PatchTarget(path=new_raw, creates_file=creates))
        elif line.startswith("@@"):
            if _HUNK_HEADER.match(line):
                hunks += 1
            else:
                malformed.append(line.strip())

    return targets, hunks, malformed


def verify_fix_applies(patch_text: object, target_files: object) -> VerificationResult:
    """Does the produced patch parse as a unified diff over files that exist?

    ``target_files`` is the inventory of paths at the revision the patch is
    meant to apply to. This is a static check, not ``git apply``: it answers
    "is this a real patch against real files", which is the failure mode an
    agent actually produces — a plausible-looking diff against a path it
    invented, or prose wrapped in fences that never was a diff.

    Call this only for cases that ask for a patch. A case with no remediation
    expectation should omit the axis rather than pass an empty patch here,
    which would (correctly) be reported as a failure.
    """
    axis = "fix_applies"

    inventory = _as_string_set(target_files)
    if inventory is None:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.NOT_MEASURED,
            reason="No file inventory was supplied, so the patch's targets cannot be checked.",
        )
    if not inventory:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.NOT_MEASURED,
            reason="The supplied file inventory is empty, so no patch target could be confirmed to exist.",
        )

    patch = _as_text(patch_text)
    if patch is None:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=f"No patch text was produced (got {type(patch_text).__name__}, expected a unified diff).",
        )
    if not patch.strip():
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason="No patch was produced — the answer contains no diff to apply.",
        )

    targets, hunks, malformed = _parse_unified_diff(patch)

    if malformed:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=f"The patch has a malformed hunk header: {malformed[0]!r} is not a valid `@@ -a,b +c,d @@` line.",
            evidence=tuple(malformed),
        )
    if not targets:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=(
                "The answer is not a unified diff — it has no `--- ` / `+++ ` file headers, "
                "so there is nothing to apply."
            ),
        )
    if hunks == 0:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=(
                "The patch names files but contains no `@@` hunks, so it changes nothing — "
                "a diff header without a hunk is not an applicable patch."
            ),
            evidence=tuple(_display_path(target.path) for target in targets),
        )

    known = {_normalise_path(path) for path in inventory}
    unknown = [
        _display_path(target.path)
        for target in targets
        if not target.creates_file and not (known & set(_path_candidates(target.path)))
    ]
    if unknown:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=(
                f"The patch targets {len(unknown)} file(s) that do not exist at the target revision: "
                f"{', '.join(sorted(unknown))}."
            ),
            evidence=tuple(sorted(unknown)),
        )

    touched = tuple(_display_path(target.path) for target in targets)
    return VerificationResult(
        axis=axis,
        outcome=Outcome.PASSED,
        reason=(
            f"The patch parses as a unified diff ({hunks} hunk(s)) and every target file exists: {', '.join(touched)}."
        ),
        evidence=touched,
    )


# ── no_fabricated_asset ──────────────────────────────────────────────────────


def _extract_asset_references(text: str) -> tuple[str, ...]:
    """Pull ARN/URN-shaped tokens out of prose, conservatively.

    Extraction is biased hard towards MISSING a reference rather than inventing
    one. Only the two schemes ``AssetUrn`` actually produces are recognised;
    bare resource names ("the acme-prod-logs bucket") are not, even though some
    of them are genuine references. Widening this would start flagging ordinary
    English as a fabricated asset.

    That bias is asymmetric on purpose. A false accusation of fabrication tells
    a customer their agent invented infrastructure when it did not — the single
    most damaging thing this surface could say wrongly — while a missed one
    costs an observation, and D9's tiers already refuse to conclude from few
    observations.
    """
    seen: list[str] = []
    for match in _ASSET_REFERENCE.finditer(text):
        token = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if token.count(":") < 2:
            continue  # `urn:something` alone names no resource
        if token not in seen:
            seen.append(token)
    return tuple(seen)


def _resolves(reference: str, known: set[str]) -> bool:
    """Is ``reference`` a known asset, or a sub-resource of one?

    Case is ignored, and a token that extends a known URN by ``/`` or ``:`` —
    an object key under a known bucket, a version under a known secret — counts
    as resolving. Its parent is in the inventory, so it is not fabricated
    infrastructure, and calling it one would be the false accusation above.
    """
    candidate = reference.casefold().rstrip("/")
    if candidate in known:
        return True
    return any(candidate.startswith(f"{owned}/") or candidate.startswith(f"{owned}:") for owned in known)


def verify_no_fabricated_asset(output_text: object, known_asset_urns: object) -> VerificationResult:
    """Does every asset the answer references actually exist in this workspace?

    The failure this catches is the one security buyers distrust most: an agent
    that writes a confident paragraph about a bucket, role or repository that
    was never in the account. It is mechanical — the inventory either contains
    the URN or it does not — so it never goes near the judge.
    """
    axis = "no_fabricated_asset"

    inventory = _as_string_set(known_asset_urns)
    if inventory is None:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.NOT_MEASURED,
            reason="No asset inventory was supplied, so a fabricated URN cannot be told from a real one.",
        )
    if not inventory:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.NOT_MEASURED,
            reason=(
                "The workspace's asset inventory is empty, so every reference would look fabricated. "
                "Not measured rather than failed — an empty inventory is our gap, not the agent's."
            ),
        )

    output = _as_text(output_text)
    if output is None:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.NOT_MEASURED,
            reason=f"No output text to inspect (got {type(output_text).__name__}), so no reference could be checked.",
        )

    references = _extract_asset_references(output)
    if not references:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.PASSED,
            reason="The answer references no asset URNs, so it fabricated none.",
        )

    known = {urn.casefold().rstrip("/") for urn in inventory}
    fabricated = [reference for reference in references if not _resolves(reference, known)]
    if fabricated:
        return VerificationResult(
            axis=axis,
            outcome=Outcome.FAILED,
            reason=(
                f"The answer references {len(fabricated)} asset(s) that do not exist in this workspace: "
                f"{', '.join(fabricated)}."
            ),
            evidence=tuple(fabricated),
        )

    return VerificationResult(
        axis=axis,
        outcome=Outcome.PASSED,
        reason=f"All {len(references)} referenced asset(s) resolve in this workspace: {', '.join(references)}.",
        evidence=references,
    )


__all__ = [
    "Outcome",
    "VerificationResult",
    "verify_fix_applies",
    "verify_no_fabricated_asset",
]
