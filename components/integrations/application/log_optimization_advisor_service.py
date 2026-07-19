"""Recommendation advisor for detected log-optimization patterns.

The LLM step that runs STRICTLY AFTER the deterministic temporal analyzer
(``log_pattern_analyzer``) has confirmed a pattern is high-frequency AND
sustained — never over the raw firehose (the POC hard rule). One measured
pattern in, one concrete tuning recommendation out: what to change and the
resource win, so an optimization card arrives with an actionable answer, not
just "this is noisy".

Grounded + honest, same construction as ``LogFixAdvisor``:
- The model sees ONLY this pattern's measured facts (kind, subject, frequency).
- The prompt forbids invented specifics — it must reason from the numbers given
  and flag low confidence when the pattern alone can't justify a change.
- Every failure mode degrades to ``None`` so the finding still files; the
  recommendation is an enhancement, never a gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_TOKENS = 320
_TEMPERATURE = 0.1

_SYSTEM = (
    "You are a senior SRE optimizing a noisy production log stream. You are given "
    "ONE recurring log pattern with measured frequency data (kind, subject, how "
    "many times it fired in the last window, how many observation runs it has "
    "persisted across, its share of window volume). Respond with STRICT JSON and "
    "nothing else, shaped exactly:\n"
    '{"assessment": "<one sentence: why this pattern is wasteful/noisy>", '
    '"recommendation": "<one or two concrete actions, e.g. \'raise the beat '
    "interval from */5 to */15', 'sample health checks at 10%', 'drop DEBUG "
    'housekeeping logs\'>", "resource_win": "<the expected saving, e.g. \'~66% '
    'fewer scheduler wakeups\'>", "confidence": "high|medium|low"}\n'
    "Rules: reason ONLY from the numbers given — do not invent an interval you "
    "were not shown; if the current schedule is unknown, phrase the change "
    "relatively ('roughly halve the frequency'). If the data can't justify a "
    "change, say so and set confidence low. No preamble, no markdown, JSON only."
)


@dataclass(frozen=True)
class OptimizationSuggestion:
    assessment: str
    recommendation: str
    resource_win: str
    confidence: str  # high | medium | low

    def as_dict(self) -> dict:
        return {
            "assessment": self.assessment,
            "recommendation": self.recommendation,
            "resource_win": self.resource_win,
            "confidence": self.confidence,
        }


class LogOptimizationAdvisor:
    """Turns one confirmed high-frequency pattern into a concrete tuning rec."""

    def __init__(self, llm_port=None) -> None:
        self._llm = llm_port

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

        provider = AILlmProvider()
        try:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
        except TypeError:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE)
        return self._llm

    def suggest(
        self,
        *,
        service: str,
        kind: str,
        subject: str,
        last_window_count: int,
        runs_observed: int,
        share_pct: float = 0.0,
        feedback: str = "",
    ) -> OptimizationSuggestion | None:
        """Return a grounded optimization suggestion, or ``None`` if unavailable.

        ``feedback`` (set on a re-advise after the grounded verifier rejected the
        first attempt) is threaded into the prompt so the second attempt is a
        genuine correction, not an identical re-run.

        Never raises — a filed finding must not depend on the LLM being up.
        """
        prompt = (
            f"kind: {kind}\n"
            f"subject: {subject}\n"
            f"service: {service}\n"
            f"fired_last_window: {last_window_count}\n"
            f"runs_observed: {runs_observed}\n"
            f"share_of_window_pct: {share_pct}\n\n"
        )
        if feedback:
            prompt += (
                f"Your previous recommendation was rejected as ungrounded: {feedback}\n"
                "Produce a more specific, grounded recommendation this time.\n\n"
            )
        prompt += "Return the JSON now."
        try:
            llm = self._get_llm()
            response = llm.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            logger.exception("log_optimization_advisor llm call failed service=%s subject=%s", service, subject)
            return None

        return self._parse(getattr(response, "content", "") or "", service)

    @staticmethod
    def _parse(content: str, service: str) -> OptimizationSuggestion | None:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning("log_optimization_advisor unparseable output service=%s", service)
            return None
        recommendation = str(data.get("recommendation") or "").strip()
        if not recommendation:
            return None
        confidence = str(data.get("confidence") or "low").lower()
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        return OptimizationSuggestion(
            assessment=str(data.get("assessment") or "").strip(),
            recommendation=recommendation,
            resource_win=str(data.get("resource_win") or "").strip(),
            confidence=confidence,
        )
