"""Suggested-fix advisor for detected log errors.

This is the LLM step that runs STRICTLY AFTER the deterministic detector
(``LogIngestService``) has confirmed and deduped a real error — never over the
raw firehose (the POC hard rule). One confirmed error in, one concise
remediation out: a root-cause hypothesis + a concrete next step the operator
can action, so a filed finding arrives with an answer attached, not just an
alarm.

Grounded + honest by construction:
- The model sees ONLY the one error's service/level/message, so it can't drift
  onto unrelated context.
- The prompt forbids invented certainty — an unknown cause must be stated as a
  hypothesis, and the model is told to say so when the line is insufficient.
- Every failure mode (no API key, LLM error, empty/garbage output) degrades to
  ``None`` so the finding still files; the suggestion is an enhancement, never a
  gate on alerting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Kept deliberately small — this runs per confirmed error, so cost + latency
# matter. A short, structured answer is more useful on a HUD card than prose.
_MAX_TOKENS = 320
_TEMPERATURE = 0.1

_SYSTEM = (
    "You are a senior SRE/SOC analyst triaging a single production log error. "
    "You are given ONE log line (service, level, message). Respond with STRICT "
    "JSON and nothing else, shaped exactly:\n"
    '{"likely_cause": "<one sentence, the most probable root cause>", '
    '"suggested_fix": "<one or two concrete, actionable steps an on-call '
    'engineer would take>", "confidence": "high|medium|low"}\n'
    "Rules: Be specific to THIS error — name the module/config/dependency in "
    "the message when present. If the line is insufficient to diagnose, say so "
    "in likely_cause and set confidence to low; never invent a cause. No "
    "preamble, no markdown, JSON only."
)


@dataclass(frozen=True)
class FixSuggestion:
    likely_cause: str
    suggested_fix: str
    confidence: str  # high | medium | low

    def as_dict(self) -> dict:
        return {
            "likely_cause": self.likely_cause,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
        }


class LogFixAdvisor:
    """Turns one confirmed log error into a concise, grounded remediation."""

    def __init__(self, llm_port=None) -> None:
        # Lazy — only resolve an LLM when actually asked to advise, so importing
        # this module never forces the knowledge stack to load.
        self._llm = llm_port

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

        # Adapters accept different construction kwargs (OpenAI: temperature
        # only; Anthropic: also max_tokens). Try the richer signature, fall
        # back to the minimal one — the JSON prompt already bounds output length.
        provider = AILlmProvider()
        try:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS)
        except TypeError:
            self._llm = provider.get_default_port(temperature=_TEMPERATURE)
        return self._llm

    def suggest(self, *, service: str, level: str, message: str, feedback: str = "") -> FixSuggestion | None:
        """Return a grounded fix suggestion, or ``None`` if unavailable.

        ``feedback`` (set on a re-advise after the grounded verifier rejected the
        first attempt) is threaded into the prompt so the second attempt is a
        genuine correction, not an identical re-run.

        Never raises — a filed finding must not depend on the LLM being up.
        """
        prompt = f"service: {service}\nlevel: {level}\nmessage: {message[:1600]}\n\n"
        if feedback:
            prompt += (
                f"Your previous suggestion was rejected as ungrounded: {feedback}\n"
                "Produce a more specific, grounded suggestion this time.\n\n"
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
            logger.exception("log_fix_advisor llm call failed service=%s", service)
            return None

        return self._parse(getattr(response, "content", "") or "", service)

    @staticmethod
    def _parse(content: str, service: str) -> FixSuggestion | None:
        text = content.strip()
        # Tolerate a model that wraps JSON in a code fence despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        # Salvage the JSON object if the model added stray prose around it.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning("log_fix_advisor unparseable output service=%s", service)
            return None
        cause = str(data.get("likely_cause") or "").strip()
        fix = str(data.get("suggested_fix") or "").strip()
        if not fix:
            return None
        confidence = str(data.get("confidence") or "low").lower()
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        return FixSuggestion(likely_cause=cause, suggested_fix=fix, confidence=confidence)
