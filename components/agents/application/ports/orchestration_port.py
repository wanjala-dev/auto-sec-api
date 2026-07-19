"""
Port for multi-agent orchestration.

Abstracts the orchestration engine that coordinates multiple agents,
runs detectors, and manages complex multi-step plans.  LangChain uses
LangGraph ``StateGraph``; LlamaIndex uses its workflow engine; CrewAI
has its own crew orchestrator.  This port hides those differences.

NOTE: ``DeepRunPort`` (in ``components.agents.ports``) already covers
plan-level deep runs.  This port covers the higher-level orchestration
— the *OrchestratorAgent* pattern that routes signals to domain agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Value objects ─────────────────────────────────────────────────────

@dataclass
class DetectorSignal:
    """A signal produced by a detector during orchestration."""

    detector_slug: str
    signal_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class OrchestrationResult:
    """Framework-agnostic result of an orchestration run."""

    signals: List[DetectorSignal] = field(default_factory=list)
    actions_created: int = 0
    agent_responses: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Port contract ─────────────────────────────────────────────────────

class OrchestrationPort(ABC):
    """
    Contract for multi-agent orchestration engines.

    Adapters live at ``infrastructure/adapters/<framework>/orchestration.py``.
    """

    @abstractmethod
    def orchestrate(
        self,
        query: str,
        *,
        user_id: str,
        workspace_id: str,
        agent_id: Optional[str] = None,
        department_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> OrchestrationResult:
        """Run the full orchestration cycle (detectors → signals → agents)."""

    @abstractmethod
    def invoke_domain_agent(
        self,
        agent_type: str,
        query: str,
        *,
        user_id: str,
        workspace_id: str,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Delegate a query to a specific domain agent within orchestration."""
