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

# The salient-token heuristic moved to the shared kernel so the integrations
# patch advisor can ground against the SAME tokens without a cross-context
# infrastructure import. This module keeps its public name (`_salient_tokens`)
# so existing callers/tests are untouched.
from components.shared_kernel.utils.salient_tokens import salient_tokens

_LOG_WATCH_SOURCE = "ai.log_watch"
_LOG_OPTIMIZATION_SOURCE = "ai.log_optimization"
_CLOUD_EXPOSURE_SOURCE = "ai.cloud_exposure"
_CONTAINER_SECURITY_SOURCE = "ai.container_security"
_CODE_SECURITY_SOURCE = "ai.code_security"

# Language keywords carry no finding-specific signal — a fix saying "return" or
# "table" proves nothing about THIS finding.
_CODE_KEYWORDS = frozenset(
    {
        "true",
        "false",
        "none",
        "null",
        "self",
        "this",
        "from",
        "import",
        "return",
        "class",
        "def",
        "func",
        "function",
        "const",
        "let",
        "var",
        "public",
        "private",
        "static",
        "void",
        "with",
        "else",
        "elif",
        "then",
        "while",
        "table",
        "select",
        "where",
        "value",
        "string",
        "print",
    }
)

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
    return salient_tokens(text)


def _code_identifiers(code: str) -> set[str]:
    """Lower-cased identifiers from a code snippet, for SAST grounding.

    Keeps dotted/underscored names of 4+ chars (``cursor.execute``, ``mark_safe``,
    ``os.system``) and drops language keywords, which carry no finding-specific
    signal. Deterministic, zero LLM — the same discipline as ``_salient_tokens``,
    just tuned for code rather than tracebacks.
    """
    if not code:
        return set()
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}(?:\.[A-Za-z_][A-Za-z0-9_]+)*", code)
    return {token.lower() for token in raw if token.lower() not in _CODE_KEYWORDS}


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

    if source_type == _CLOUD_EXPOSURE_SOURCE:
        # For an attack-path finding the grounding anchor is the named path: the
        # remediation must reference the actual exposed entry and/or the crown-jewel
        # target — not generic "restrict access" boilerplate that fits any path.
        named = [
            n
            for n in (str(payload.get("entry") or "").strip().lower(), str(payload.get("target") or "").strip().lower())
            if n
        ]
        if not named:
            return VerifyResult(grounded=True, reason="")  # no checkable specifics
        if any(n in text_l for n in named):
            return VerifyResult(grounded=True, reason="")
        sample = " / ".join(n for n in (payload.get("entry"), payload.get("target")) if n)
        return VerifyResult(
            grounded=False,
            reason=(
                f"The remediation names neither end of the attack path ({sample}) and reads as generic. "
                "Name the exposed entry and/or the reachable target the fix breaks."
            ),
        )

    if source_type == _CONTAINER_SECURITY_SOURCE:
        # For a container CVE the grounding anchor is the fix that Trivy already told us:
        # the remediation must name the package, the CVE id, or the fixed version — not
        # generic "update your dependencies" boilerplate.
        anchors = [
            a
            for a in (
                str(payload.get("pkg_name") or "").strip().lower(),
                str(payload.get("vulnerability_id") or "").strip().lower(),
                str(payload.get("fixed_version") or "").strip().lower(),
            )
            if a
        ]
        if not anchors:
            return VerifyResult(grounded=True, reason="")  # no checkable specifics
        if any(a in text_l for a in anchors):
            return VerifyResult(grounded=True, reason="")
        sample = " / ".join(
            s for s in (payload.get("pkg_name"), payload.get("vulnerability_id"), payload.get("fixed_version")) if s
        )
        return VerifyResult(
            grounded=False,
            reason=(
                f"The remediation names none of the CVE's specifics ({sample}) and reads as generic. "
                "Name the affected package, the CVE id, or the fixed version to upgrade to."
            ),
        )

    if source_type == _CODE_SECURITY_SOURCE:
        # For a SAST finding the grounding anchors are the scanner's own facts:
        # the rule id, the flagged file, and the matched snippet's identifiers. A
        # fix that references none of them is boilerplate that fits any finding.
        rule_id = str(payload.get("rule_id") or "").strip().lower()
        rule_label = rule_id.rsplit(".", 1)[-1] if rule_id else ""
        path = str(payload.get("path") or "").strip().lower()
        path_base = path.rsplit("/", 1)[-1] if path else ""
        snippet = str(payload.get("snippet") or "")
        # Code identifiers, not log symbols: ``salient_tokens`` targets dotted
        # module paths / underscored names from tracebacks and returns nothing for
        # an ordinary code line like ``cursor.execute("DROP TABLE %s" % table)``.
        # SAST evidence IS code, so extract its identifiers directly.
        anchors = {a for a in (rule_id, rule_label, path, path_base) if a} | _code_identifiers(snippet)
        if not anchors:
            return VerifyResult(grounded=True, reason="")  # no checkable specifics
        if any(a in text_l for a in anchors):
            return VerifyResult(grounded=True, reason="")
        # A fix that quotes the offending line verbatim is grounded by construction.
        snippet_norm = " ".join(snippet.split()).lower()
        if len(snippet_norm) >= 12 and snippet_norm[:160] in " ".join(text_l.split()):
            return VerifyResult(grounded=True, reason="")
        sample = ", ".join(s for s in (rule_label or rule_id, path_base or path) if s)
        return VerifyResult(
            grounded=False,
            reason=(
                f"The fix references none of the finding's specifics (e.g. {sample}) and reads as "
                "generic. Name the rule, the flagged file, or an identifier from the matched snippet."
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
