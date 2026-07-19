"""Provider for the writing AI adapter.

Controllers (e.g. ``components/content/api/ai_draft_controller.py``)
ask this provider for an adapter instance instead of importing the
concrete ``LangchainWritingAiAdapter`` directly. Keeps the API layer
free of infrastructure imports — the
``test_controllers_do_not_import_concrete_adapters`` architecture test
enforces this rule.

The adapter is lazy-imported inside the factory method so module load
is cheap and tests can monkeypatch ``provider.adapter()`` without
dragging LangChain into test discovery.
"""

from __future__ import annotations

from typing import Any


class WritingAiProvider:
    """Driving-side façade for the content writing-AI adapter."""

    def adapter(self) -> Any:
        """Return a fresh ``LangchainWritingAiAdapter`` instance."""
        from components.content.infrastructure.adapters.langchain_writing_ai_adapter import (
            LangchainWritingAiAdapter,
        )

        return LangchainWritingAiAdapter()


_default = WritingAiProvider()


def get_writing_ai_provider() -> WritingAiProvider:
    """Return the default provider — composition root for the content
    writing-AI adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
