"""ModelSelectionPolicy — domain policy for LLM model tiering.

Evaluates a tool invocation request and determines which model tier
is appropriate.  The LLM provider registry then resolves the tier
to a concrete model slug at runtime (e.g. tier_1 → gpt-4o-mini,
tier_3 → claude-opus-4-6).

This is a pure domain policy — no ORM, no framework imports.
Business rules live here so that cost optimisation is a first-class
domain concern rather than an infrastructure afterthought.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from components.agents.domain.enums import ModelTier


# ── Operations classified by complexity ──────────────────────────────

_TIER_1_OPERATIONS: FrozenSet[str] = frozenset({
    "list",
    "get",
    "search",
    "count",
    "classify",
    "extract",
    "validate",
    "lookup",
    "filter",
})

_TIER_2_OPERATIONS: FrozenSet[str] = frozenset({
    "summarize",
    "describe",
    "compare",
    "translate",
    "format",
    "transform",
    "generate_template",
    "draft",
})

_TIER_3_OPERATIONS: FrozenSet[str] = frozenset({
    "plan",
    "reason",
    "analyze",
    "code_generate",
    "multi_step",
    "create_strategy",
    "deep_run",
    "orchestrate",
    "synthesize",
})


@dataclass(frozen=True)
class ModelSelectionResult:
    """Output of the model selection policy."""

    tier: str
    reason: str
    override_model: Optional[str] = None  # Explicit model if policy demands it

    @property
    def cost_multiplier(self) -> float:
        return ModelTier.COST_MULTIPLIERS.get(self.tier, 1.0)


class ModelSelectionPolicy:
    """Evaluates a tool execution request and selects the cheapest
    adequate model tier.

    Evaluation order (first match wins):
    1. Explicit tier override in tool config → honour it.
    2. Operation name matches a known tier bucket → use that tier.
    3. Heuristic: large param payloads or complex schemas → bump tier.
    4. Default → tier_2 (safe middle ground).
    """

    # Param-size thresholds (bytes) that suggest higher complexity
    _LARGE_PAYLOAD_BYTES = 4_000
    _VERY_LARGE_PAYLOAD_BYTES = 16_000

    def evaluate(
        self,
        *,
        operation: str,
        params: Dict[str, Any],
        tool_config: Dict[str, Any],
        agent_type: str = "",
    ) -> ModelSelectionResult:
        """Return the recommended model tier for this invocation."""

        # 1. Explicit override in tool config
        forced_tier = tool_config.get("model_tier")
        if forced_tier and forced_tier in ModelTier.ALL:
            return ModelSelectionResult(
                tier=forced_tier,
                reason=f"tool config forces {forced_tier}",
            )

        forced_model = tool_config.get("model_name")
        if forced_model:
            return ModelSelectionResult(
                tier=ModelTier.TIER_2,
                reason=f"tool config forces model {forced_model}",
                override_model=forced_model,
            )

        # 2. Operation-name classification
        op = operation.lower().strip()
        if op in _TIER_1_OPERATIONS:
            return ModelSelectionResult(
                tier=ModelTier.TIER_1,
                reason=f"operation '{op}' classified as simple",
            )
        if op in _TIER_3_OPERATIONS:
            return ModelSelectionResult(
                tier=ModelTier.TIER_3,
                reason=f"operation '{op}' classified as complex",
            )
        if op in _TIER_2_OPERATIONS:
            return ModelSelectionResult(
                tier=ModelTier.TIER_2,
                reason=f"operation '{op}' classified as moderate",
            )

        # 3. Payload-size heuristic
        payload_size = self._estimate_payload_size(params)
        if payload_size > self._VERY_LARGE_PAYLOAD_BYTES:
            return ModelSelectionResult(
                tier=ModelTier.TIER_3,
                reason=f"payload size ({payload_size}B) suggests complex task",
            )
        if payload_size > self._LARGE_PAYLOAD_BYTES:
            return ModelSelectionResult(
                tier=ModelTier.TIER_2,
                reason=f"payload size ({payload_size}B) suggests moderate task",
            )

        # 4. Default
        return ModelSelectionResult(
            tier=ModelTier.TIER_2,
            reason="default tier for unclassified operation",
        )

    @staticmethod
    def _estimate_payload_size(params: Dict[str, Any]) -> int:
        """Quick byte-size estimate without heavy serialisation."""
        import json

        try:
            return len(json.dumps(params, default=str))
        except (TypeError, ValueError):
            return 0
