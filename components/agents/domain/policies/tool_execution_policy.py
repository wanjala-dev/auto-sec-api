"""ToolExecutionPolicy — decides whether a tool call needs an LLM.

Before routing a tool invocation through the (expensive) LLM pipeline,
this policy evaluates the request and determines whether deterministic
rules-based logic can handle it directly.

Examples of rules-based shortcuts:
- "list budgets" with no filters → direct ORM query, no reasoning needed.
- "get task by id" → simple lookup, skip the LLM.
- Cached identical queries within TTL → serve from cache.

This is a pure domain policy — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional

from components.agents.domain.enums import ExecutionMode


# ── Operations that never need LLM reasoning ─────────────────────────

_DETERMINISTIC_OPERATIONS: FrozenSet[str] = frozenset({
    "list",
    "get",
    "count",
    "lookup",
    "filter",
    "exists",
    "health_check",
    "schema",
    "status",
})

# Operations that always require LLM reasoning
_LLM_REQUIRED_OPERATIONS: FrozenSet[str] = frozenset({
    "summarize",
    "analyze",
    "plan",
    "reason",
    "code_generate",
    "multi_step",
    "synthesize",
    "orchestrate",
    "deep_run",
    "draft",
    "create_strategy",
})


@dataclass(frozen=True)
class ExecutionModeDecision:
    """Output of the tool execution policy."""

    mode: str                     # ExecutionMode value
    reason: str
    cache_key: Optional[str] = None   # Non-None when mode is CACHED
    ttl_seconds: int = 0              # Cache TTL when applicable

    @property
    def is_llm_required(self) -> bool:
        return self.mode == ExecutionMode.LLM

    @property
    def is_cacheable(self) -> bool:
        return self.mode == ExecutionMode.CACHED

    @property
    def is_rules_based(self) -> bool:
        return self.mode == ExecutionMode.RULES_BASED


class ToolExecutionPolicy:
    """Evaluate whether a tool invocation can skip the LLM.

    Evaluation order (first match wins):
    1. Tool config forces LLM → always use LLM.
    2. Cache check: identical (tool, operation, params) within TTL → CACHED.
    3. Operation is in the deterministic set AND params are simple → RULES_BASED.
    4. Operation is in the LLM-required set → LLM.
    5. Heuristic: natural-language params (long strings, questions) → LLM.
    6. Default → LLM (safe fallback).
    """

    # If any param value exceeds this length, assume it contains
    # natural-language content that needs LLM interpretation.
    _NL_PARAM_LENGTH_THRESHOLD = 200

    # Default cache TTL for deterministic operations (seconds)
    _DEFAULT_CACHE_TTL = 300  # 5 minutes

    def evaluate(
        self,
        *,
        operation: str,
        params: Dict[str, Any],
        tool_config: Dict[str, Any],
        access_strategy: str,
        recent_cache_keys: FrozenSet[str] | None = None,
    ) -> ExecutionModeDecision:
        """Return the recommended execution mode for this invocation."""

        # 1. Tool config forces LLM
        if tool_config.get("require_llm", False):
            return ExecutionModeDecision(
                mode=ExecutionMode.LLM,
                reason="tool config requires LLM",
            )

        op = operation.lower().strip()

        # 2. Cache check
        cache_key = self._build_cache_key(
            operation=op,
            params=params,
            access_strategy=access_strategy,
        )
        if recent_cache_keys and cache_key in recent_cache_keys:
            return ExecutionModeDecision(
                mode=ExecutionMode.CACHED,
                reason=f"identical request cached (key={cache_key[:16]}...)",
                cache_key=cache_key,
                ttl_seconds=self._DEFAULT_CACHE_TTL,
            )

        # 3. Deterministic operations with simple params
        if op in _DETERMINISTIC_OPERATIONS and not self._has_nl_params(params):
            return ExecutionModeDecision(
                mode=ExecutionMode.RULES_BASED,
                reason=f"operation '{op}' is deterministic with simple params",
                cache_key=cache_key,
                ttl_seconds=self._DEFAULT_CACHE_TTL,
            )

        # 4. Explicitly LLM-required
        if op in _LLM_REQUIRED_OPERATIONS:
            return ExecutionModeDecision(
                mode=ExecutionMode.LLM,
                reason=f"operation '{op}' requires LLM reasoning",
            )

        # 5. Natural-language heuristic
        if self._has_nl_params(params):
            return ExecutionModeDecision(
                mode=ExecutionMode.LLM,
                reason="params contain natural-language content",
            )

        # 6. Default fallback
        return ExecutionModeDecision(
            mode=ExecutionMode.LLM,
            reason="default: unclassified operation",
        )

    def _has_nl_params(self, params: Dict[str, Any]) -> bool:
        """Detect if any param looks like natural-language input."""
        for value in params.values():
            if isinstance(value, str) and len(value) > self._NL_PARAM_LENGTH_THRESHOLD:
                return True
            if isinstance(value, str) and "?" in value:
                # Likely a question/query
                return True
        return False

    @staticmethod
    def _build_cache_key(
        *,
        operation: str,
        params: Dict[str, Any],
        access_strategy: str,
    ) -> str:
        """Build a deterministic cache key from the request signature."""
        import hashlib
        import json

        payload = json.dumps(
            {"op": operation, "strategy": access_strategy, "params": params},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
