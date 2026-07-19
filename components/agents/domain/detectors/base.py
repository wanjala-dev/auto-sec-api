"""Domain-level detector abstractions.

These are pure domain concepts — no ORM, no persistence imports.
Concrete detector implementations live in ``infrastructure/adapters/actions/detectors/``
(they *do* touch the ORM), but the contracts themselves belong here.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

# Domain constant — mirrors the persistence layer value but avoids the import.
ACTION_STATUS_PENDING = "pending"


@dataclass
class DetectorContext:
    """Runtime context shared with detectors."""

    workspace_id: str
    teammate_id: str
    run_at: datetime
    last_run_at: Optional[datetime]
    config: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)
    invoke_agent: Optional[Callable[[str, str, Optional[Dict[str, Any]]], Dict[str, Any]]] = None


@dataclass
class DetectorResult:
    """Structured description of an AI action suggestion."""

    action_type: str
    title: str
    summary: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    status: str = ACTION_STATUS_PENDING
    detector_slug: Optional[str] = None
    agent_type: Optional[str] = None
    auto_execute: bool = False
    performed_by_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None


class DetectorSignal:
    """Lightweight signal that can be consumed by the teammate LLM."""

    def __init__(self, signal_type: str, payload: Dict[str, Any]) -> None:
        self.signal_type = signal_type
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return {"signal_type": self.signal_type, "payload": self.payload}


class BaseDetector(abc.ABC):
    """Abstract detector that finds opportunities for automations."""

    slug: str = "base"
    name: str = "Base Detector"
    cadence: str = "default"
    description: str = ""
    default_config: Dict[str, Any] = {}

    def __init__(self, *, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def should_run(self, context: DetectorContext) -> bool:
        """Return whether this detector should execute for the given context."""
        return True

    def gather_signals(self, context: DetectorContext) -> List[DetectorSignal]:
        """Optional hook for emitting lightweight signals."""
        return []

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        """Legacy execution interface; default no-op."""
        return []


__all__ = [
    "ACTION_STATUS_PENDING",
    "BaseDetector",
    "DetectorContext",
    "DetectorResult",
    "DetectorSignal",
]
