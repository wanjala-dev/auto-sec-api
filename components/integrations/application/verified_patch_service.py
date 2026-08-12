"""Rebuild the file from the patch the deep run ALREADY graded (ADR 0025 Phase 2).

The draft-PR engine used to author its patch twice. The specialist's deep run
produced a ``fix_before`` → ``fix_after`` snippet that was graded by
``RubricMiddleware`` and validated by the deterministic oracles
(``check_patch`` / the remediation anti-patterns), stamped it on the card — and
then ``OpenDraftPrUseCase`` threw it away and asked ``SastPatchAdvisor`` for a
fresh full-file rewrite. The rewrite is a DIFFERENT artifact from a DIFFERENT
prompt: nothing the rubric said about the graded snippet constrained the code we
actually committed. The grader's verdict decided nothing.

This module closes that gap. It applies the graded snippet to the current file
mechanically — no model, no second opinion — so the committed patch is the one
the rubric passed. The advisor stays as the FALLBACK for cards that carry no
usable snippet (an honest empty ``fix_before``, or a file that has moved on since
triage); it is no longer the default author.

**Strict, but not a gate.** Matching fails closed *for this strategy only*: an
absent, ambiguous, or drifted ``fix_before`` returns ``None`` and the caller
falls through to the advisor. It never withholds the artifact — a finding in a
connected repo always gets its draft PR. What it refuses to do is guess: no fuzzy
matching, no "closest" hunk, no silent partial application. Anything less exact
than "these lines, once, here" is not the graded patch and must not be committed
as if it were.

Whatever this returns still runs the shared ``validate_patch`` +
``validate_patch_scope`` chain in the use case. Being rubric-graded upstream
authorises nothing — the safety gates are unchanged and unconditional.
"""

from __future__ import annotations

import logging

from components.integrations.application.log_patch_advisor_service import PatchProposal

logger = logging.getLogger(__name__)

#: How far a match may sit from the finding's flagged span and still be treated
#: as "the" occurrence when the snippet appears more than once in the file. A
#: duplicated idiom (the same ``jwt.decode(...)`` line in three handlers) is
#: exactly the case where committing the wrong one would be silent and wrong.
_ANCHOR_WINDOW_LINES = 60


def _norm_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _base_indent(lines: list[str]) -> str:
    """The common leading whitespace of the non-blank lines, as a prefix string."""
    indents = [line[: len(line) - len(line.lstrip())] for line in lines if line.strip()]
    if not indents:
        return ""
    shortest = min(indents, key=len)
    for indent in indents:
        if not indent.startswith(shortest):
            return ""
    return shortest


def _dedent(lines: list[str]) -> list[str]:
    indent = _base_indent(lines)
    if not indent:
        return list(lines)
    return [line[len(indent) :] if line.startswith(indent) else line for line in lines]


def _find_matches(content_lines: list[str], before_lines: list[str]) -> list[int]:
    """Start indices (0-based) where ``before_lines`` matches, comparing stripped
    lines so the model's re-indentation of a copied snippet doesn't lose the match.

    Blank-line-only snippets never match — they would match everywhere.
    """
    needle = [line.strip() for line in before_lines]
    if not any(needle):
        return []
    haystack = [line.strip() for line in content_lines]
    span = len(needle)
    return [i for i in range(len(haystack) - span + 1) if haystack[i : i + span] == needle]


def _pick_anchored(matches: list[int], *, start_line: int) -> int | None:
    """Resolve a multi-occurrence match against the finding's own line number.

    One occurrence → it. Several → the one inside the flagged window, and only if
    exactly one qualifies. A snippet that appears twice near the finding is
    genuinely ambiguous; committing either would be a coin flip.
    """
    if len(matches) == 1:
        return matches[0]
    if not start_line:
        return None
    lo = start_line - 1 - _ANCHOR_WINDOW_LINES
    hi = start_line - 1 + _ANCHOR_WINDOW_LINES
    near = [index for index in matches if lo <= index <= hi]
    return near[0] if len(near) == 1 else None


def build_verified_proposal(*, payload: dict, path: str, current_content: str) -> PatchProposal | None:
    """The graded ``fix_before`` → ``fix_after`` applied to ``current_content``.

    Returns ``None`` — never raises — when the card carries no usable snippet or
    the file has drifted, so the caller falls through to the generating advisor.
    """
    before = _norm_newlines(str(payload.get("fix_before") or "")).strip("\n")
    after = _norm_newlines(str(payload.get("fix_after") or "")).strip("\n")
    if not before.strip() or not after.strip():
        # The honest "no concrete fix" from the specialist, or a card triaged
        # before the snippet existed. Not a failure — just nothing to reuse.
        return None
    if before == after:
        return None

    content = _norm_newlines(current_content)
    content_lines = content.split("\n")
    before_lines = before.split("\n")

    matches = _find_matches(content_lines, before_lines)
    if not matches:
        logger.info(
            "verified_patch_miss path=%s reason=snippet_absent lines=%s",
            path,
            len(before_lines),
        )
        return None

    start = _pick_anchored(matches, start_line=int(payload.get("start_line") or 0))
    if start is None:
        logger.info(
            "verified_patch_miss path=%s reason=ambiguous occurrences=%s",
            path,
            len(matches),
        )
        return None

    end = start + len(before_lines)
    # Re-indent the replacement to the block it replaces: the snippet on the card
    # was copied out of the file and may have lost its leading whitespace. Python
    # is the language where getting this wrong changes the program's meaning
    # rather than its formatting, so it is done structurally, not by eyeball.
    matched_indent = _base_indent(content_lines[start:end])
    after_lines = _dedent(after.split("\n"))
    rebuilt = [(matched_indent + line if line.strip() else line) for line in after_lines]

    updated_lines = content_lines[:start] + rebuilt + content_lines[end:]
    updated_content = "\n".join(updated_lines)
    if updated_content == content:
        return None
    if current_content.endswith("\n") and not updated_content.endswith("\n"):
        updated_content += "\n"

    logger.info(
        "verified_patch_applied path=%s start_line=%s before_lines=%s after_lines=%s",
        path,
        start + 1,
        len(before_lines),
        len(rebuilt),
    )
    return PatchProposal(
        path=path,
        updated_content=updated_content,
        change_summary=str(payload.get("suggested_fix") or "").strip()
        or "Applied the verified fix from the code-security agent's triage.",
    )
