"""SEE-205 — perceived-error detection (online eval without ground truth).

We can't grade a production agent answer against a known-correct output — there
is none. But the *transcript* often tells us the agent got it wrong: the user's
next message pushes back ("that's wrong", "that didn't work") or pastes an error
back. Detecting that signal turns raw traces into a review queue without a human
reading every one.

Pure domain: a list of ordered ``{role, content}`` messages in, the flagged
turns out. No ORM, no I/O — the detector adapter feeds it real conversations.

Precision over recall: the patterns are phrase-anchored rebuttals and pasted
errors, so a benign "how do I fix this error?" question does not trip it. A
missed rebuttal is cheap (one trace unreviewed); a false finding is expensive
(noise on the board), so the bar is deliberately high.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REBUTTAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"that(?:'s| is|s)? (?:wrong|incorrect|not right|not correct)",
        r"that(?:'s| is)?n['’]?t (?:right|correct|what i)",
        r"you(?:'re| are) wrong",
        r"\bwrong answer\b",
        r"that(?:'s| is)? not (?:what i|helpful|right|correct)",
        r"\b(?:that|it) (?:did|does|do)(?:\s?n['’]?t| not) work",
        r"\bstill (?:wrong|broken|failing|not working)",
        r"^\s*no[,.\s]+that(?:'s| is)?\b",
        r"\bnot (?:helpful|correct)\b",
        r"\bnot what i (?:asked|wanted|meant)\b",
    )
)

_ERROR_PASTE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"traceback \(most recent call last\)",
        r"^\s*[a-z_][a-z0-9_.]*error:\s",
        r"\bexception\b[^.\n]{0,40}\bline\s+\d+",
    )
)

_ROLE_USER = "user"
_ROLE_ASSISTANT = "assistant"


@dataclass(frozen=True)
class PerceivedError:
    """One flagged turn: an assistant answer the user pushed back on."""

    index: int  # position of the user rebuttal in the message list
    reason: str
    assistant_snippet: str
    user_snippet: str


def classify_perceived_error(text: str | None) -> str | None:
    """Return a short reason when *text* reads as a rebuttal / pasted error."""
    if not text or not text.strip():
        return None
    normalised = re.sub(r"\s+", " ", text).strip()
    for pattern in _REBUTTAL_PATTERNS:
        if pattern.search(normalised):
            return "user pushed back on the answer"
    for pattern in _ERROR_PASTE_PATTERNS:
        if pattern.search(text):  # raw text — line anchors matter
            return "user pasted an error back"
    return None


def _snippet(text: str, limit: int = 160) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    return collapsed[:limit]


def detect_perceived_errors(messages: list[dict]) -> list[PerceivedError]:
    """Flag every user turn that pushes back on the assistant turn before it.

    *messages* is the conversation in order, each ``{"role": ..., "content": ...}``.
    A rebuttal only counts when it directly follows an assistant message — a
    standalone user complaint with no preceding answer is not an agent error.
    """
    flagged: list[PerceivedError] = []
    for i in range(1, len(messages)):
        current = messages[i] or {}
        previous = messages[i - 1] or {}
        if current.get("role") != _ROLE_USER:
            continue
        if previous.get("role") != _ROLE_ASSISTANT:
            continue
        reason = classify_perceived_error(current.get("content"))
        if reason is None:
            continue
        flagged.append(
            PerceivedError(
                index=i,
                reason=reason,
                assistant_snippet=_snippet(previous.get("content", "")),
                user_snippet=_snippet(current.get("content", "")),
            )
        )
    return flagged
