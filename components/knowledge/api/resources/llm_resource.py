"""Response DTO for LLM endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMMessageResource:
    """A single message in LLM interaction."""
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponseResource:
    """Output DTO for LLM chat endpoints."""
    message: str = ""
    messages: list[LLMMessageResource] = field(default_factory=list)
    model: str | None = None
    tokens_used: int | None = None
    finish_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMProviderResource:
    """Available LLM provider information."""
    name: str
    provider: str
    models: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMProvidersResource:
    """Output DTO for LLM providers listing."""
    providers: list[LLMProviderResource] = field(default_factory=list)
    total: int = 0


@dataclass(frozen=True)
class AvailableModelResource:
    """Available LLM model information."""
    id: str
    name: str
    provider: str
    context_window: int | None = None
    cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AvailableModelsResource:
    """Output DTO for available models listing."""
    models: list[AvailableModelResource] = field(default_factory=list)
    total: int = 0
