"""Adapter: content faithfulness port → agents FaithfulnessVerifier.

Wraps the canonical groundedness checker (reached via the agents
application provider, never the agents domain directly) and maps its
report into the content-owned value object.
"""

from __future__ import annotations

from components.content.application.ports.faithfulness_check_port import (
    FaithfulnessCheckPort,
)
from components.content.domain.value_objects.faithfulness_check_result import (
    FaithfulnessCheckResult,
)


class AgentsFaithfulnessCheckAdapter(FaithfulnessCheckPort):
    """Checks figure groundedness using the agents verifier."""

    def check(
        self, *, html: str, grounding_texts: list[str]
    ) -> FaithfulnessCheckResult:
        from components.agents.application.providers.ai_provider import AIProvider

        verifier = AIProvider.build_faithfulness_verifier()
        report = verifier.verify(generated_html=html, grounding_texts=grounding_texts)
        return FaithfulnessCheckResult(
            ok=report.ok,
            unsupported_numbers=tuple(report.unsupported_numbers),
            unsupported_names=tuple(report.unsupported_names),
            checked=report.checked,
        )
