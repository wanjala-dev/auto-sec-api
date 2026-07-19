"""Provider/composition root for ORM model classes in the ``infrastructure.persistence.ai`` package.

Controllers in ``components/*/api/*.py`` must not import ORM model classes
directly (enforced by the architecture test
``test_controllers_do_not_import_concrete_adapters``). They consume
:class:`AiModelsProvider` instead, which lazy-imports each model class on
first access. This keeps the API layer's import graph free of Django ORM /
infrastructure dependencies at module load time.

Every property below resolves to an ORM model class from one of the
sub-packages of ``infrastructure.persistence.ai``:

- ``ai.llms.models`` — :class:`AIModel`
- ``ai.agents.models`` — :class:`Agent`
- ``ai.conversations.models`` —
  :class:`Conversation`, :class:`ConversationMessage`,
  :class:`AgentResponseFeedback`
- ``ai.models`` — :class:`Document`, :class:`DocumentChunk`

The provider is framework-free at the module top level — only stdlib
typing imports. All ``infrastructure.persistence`` imports happen inside
method bodies so the module is safe to import from any layer.
"""

from __future__ import annotations

from typing import Any


class AiModelsProvider:
    """Driving-side façade for ORM models in ``infrastructure.persistence.ai``.

    Each property returns the concrete Django ORM model class via a lazy
    import. Tests can monkeypatch any property on the module-level
    ``_default`` instance (or the result of
    :func:`get_ai_models_provider`) to swap a model class for a fake.
    """

    # ── llms ────────────────────────────────────────────────────────────────
    @property
    def AIModel(self) -> Any:
        from infrastructure.persistence.ai.llms.models import AIModel

        return AIModel

    # ── agents ──────────────────────────────────────────────────────────────
    @property
    def Agent(self) -> Any:
        from infrastructure.persistence.ai.agents.models import Agent

        return Agent

    # ── conversations ───────────────────────────────────────────────────────
    @property
    def Conversation(self) -> Any:
        from infrastructure.persistence.ai.conversations.models import Conversation

        return Conversation

    @property
    def ConversationMessage(self) -> Any:
        from infrastructure.persistence.ai.conversations.models import (
            ConversationMessage,
        )

        return ConversationMessage

    @property
    def AgentResponseFeedback(self) -> Any:
        from infrastructure.persistence.ai.conversations.models import (
            AgentResponseFeedback,
        )

        return AgentResponseFeedback

    # ── ai (RAG knowledge) ──────────────────────────────────────────────────
    @property
    def Document(self) -> Any:
        from infrastructure.persistence.ai.models import Document

        return Document

    @property
    def DocumentChunk(self) -> Any:
        from infrastructure.persistence.ai.models import DocumentChunk

        return DocumentChunk


_default = AiModelsProvider()


def get_ai_models_provider() -> AiModelsProvider:
    """Return the default :class:`AiModelsProvider` — composition root for
    ORM model lookups in the ``ai`` persistence package.

    Override by monkeypatching this module's ``_default`` attribute in
    tests, or by reassigning a specific property on the returned
    instance.
    """
    return _default
