"""Grounded verification of an advisor's suggestion against a finding's evidence.

This is the research-backed core of the L2 verification loop. Huang et al. (ICLR
2024, "LLMs Cannot Self-Correct Reasoning Yet") + 2026 follow-ups show that when
an LLM critiques its OWN output with no external anchor, the critique degenerates
into a *consistency* check ("does this look right?" → prior beliefs say yes) and
can make correct answers worse. The fix the research points to — and what
LangChain's RubricMiddleware operationalises via grader `tools=[...]` — is
**grounded** verification: check the answer against ground truth, not against the
model's own belief.

For a SOC finding, the ground truth is the detector's **evidence** (the error
line / symbols for a triage finding; the measured subject + frequency for an
optimization finding). This module verifies **deterministically** — zero LLM —
that the advisor's suggestion actually engages with that evidence rather than
emitting plausible boilerplate. It is conservative: it only FAILS a suggestion
when the evidence offers checkable specifics AND the suggestion references none
of them; when it can't decide, it passes (never over-blocks a real fix).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LOG_WATCH_SOURCE = "ai.log_watch"
_LOG_OPTIMIZATION_SOURCE = "ai.log_optimization"

# Generic filler that carries no grounding on its own.
_BOILERPLATE = {
    "investigate",
    "further",
    "check",
    "logs",
    "monitor",
    "monitoring",
    "system",
    "ensure",
    "proper",
    "review",
    "additional",
    "metrics",
    "inconsistencies",
    "errors",
    "error",
    "issue",
    "issues",
    "problem",
    "resources",
    "necessary",
    "perform",
    "operation",
    "data",
    "being",
    "cause",
    "may",
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "which",
    "have",
    "will",
    "should",
}
# CamelCase identifiers (ImportError, AiEmbeddingsProvider), dotted paths
# (components.knowledge.x), and longer snake_case (refresh_recommendable_items).
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")
_DOTTED_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.\w+){2,}\b")
_SNAKE_RE = re.compile(r"\b[a-z]+_[a-z_]{3,}\b")

# A concrete optimization change (vs "reduce noise" hand-waving).
_CONCRETE_CHANGE = (
    "interval",
    "frequenc",
    "reduce",
    "sampl",
    "drop",
    "disable",
    "every",
    "minute",
    "hour",
    "cron",
    "schedul",
    "throttl",
    " rate",
    "verbos",
    "log level",
    "loglevel",
    "debug",
    "batch",
    "cache",
    "backoff",
    "*/",
)


@dataclass(frozen=True)
class VerifyResult:
    grounded: bool
    reason: str  # empty when grounded


def _salient_tokens(text: str) -> set[str]:
    """Code-like identifiers from the finding's ground truth (message/evidence)."""
    tokens: set[str] = set()
    for rx in (_CAMEL_RE, _DOTTED_RE, _SNAKE_RE):
        tokens.update(rx.findall(text or ""))
    # Drop pure-filler snake tokens (e.g. "log_level" isn't an identity anchor).
    return {t for t in tokens if t.lower() not in _BOILERPLATE}


def _ground_text_for_triage(payload: dict) -> str:
    parts = [str(payload.get("message") or ""), str(payload.get("signal") or "")]
    for ev in payload.get("evidence") or []:
        if isinstance(ev, dict):
            parts.append(str(ev.get("detail") or ""))
    return "\n".join(parts)


def verify_suggestion(*, source_type: str, payload: dict, suggestion_text: str) -> VerifyResult:
    """Return whether ``suggestion_text`` is grounded in the finding's evidence.

    Deterministic; never raises. Conservative — passes when it cannot decide.
    """
    text = (suggestion_text or "").strip()
    if not text:
        return VerifyResult(grounded=False, reason="Empty suggestion — nothing to act on.")
    text_l = text.lower()

    if source_type == _LOG_OPTIMIZATION_SOURCE:
        # For an optimization rec the grounding anchor is a CONCRETE change tied
        # to the measured frequency (a specific interval / sampling rate / which
        # logs to drop). Vague "reduce noise / monitor the logs" advice has none.
        # We deliberately do NOT also require the rec to echo the (often long,
        # dotted) task name — that over-flags genuinely-actionable recs.
        if any(kw in text_l for kw in _CONCRETE_CHANGE):
            return VerifyResult(grounded=True, reason="")
        return VerifyResult(
            grounded=False,
            reason=(
                "The recommendation names no concrete change (a specific interval, sampling rate, "
                "or which logs to drop) and reads as generic."
            ),
        )

    # Default: triage / error findings.
    salient = _salient_tokens(_ground_text_for_triage(payload))
    service = str(payload.get("service") or "").strip()
    if not salient and not service:
        # No checkable specifics in the evidence — can't disprove groundedness.
        return VerifyResult(grounded=True, reason="")
    if (service and service.lower() in text_l) or any(tok.lower() in text_l for tok in salient):
        return VerifyResult(grounded=True, reason="")
    sample = ", ".join(list(salient)[:3]) or service
    return VerifyResult(
        grounded=False,
        reason=(
            f"The fix references none of the error's specifics (e.g. {sample}) and reads as generic. "
            "Name the actual module/symbol/service from the error line."
        ),
    )
