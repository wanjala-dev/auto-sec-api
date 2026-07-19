"""Port: check rendered copy against a grounding corpus before send.

The content context owns this interface; the infrastructure adapter wraps
the agents ``FaithfulnessVerifier`` (the canonical groundedness checker)
and maps its report into the content value object. Keeping the port here
lets the send use cases stay decoupled from the agents domain type.
"""

from __future__ import annotations

import abc

from components.content.domain.value_objects.faithfulness_check_result import (
    FaithfulnessCheckResult,
)


class FaithfulnessCheckPort(abc.ABC):
    """Checks whether the numeric figures in ``html`` are grounded."""

    @abc.abstractmethod
    def check(
        self, *, html: str, grounding_texts: list[str]
    ) -> FaithfulnessCheckResult:
        """Return the faithfulness result for ``html`` vs ``grounding_texts``."""
