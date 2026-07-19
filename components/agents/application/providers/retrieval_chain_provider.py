"""Provider/composition root for the retrieval chain primitives.

Controllers (``components/agents/api/controller.py``) consume
:class:`RetrievalChainProvider` instead of importing the concrete
LangChain adapter directly. Keeps the API layer's import graph free
of infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter symbols so module load is cheap
and tests can monkeypatch ``provider.streaming_chain_from_llm`` /
``provider.normalize_metadata_value`` without dragging in LangChain
at test discovery time.
"""

from __future__ import annotations

from typing import Any


class RetrievalChainProvider:
    """Driving-side façade for the agents retrieval-chain adapter."""

    def streaming_chain_from_llm(self, *args, **kwargs) -> Any:
        """Build a streaming retrieval chain via ``from_llm``."""
        from components.agents.infrastructure.adapters.langchain.chains.retrieval import (
            StreamingConversationalRetrievalChain,
        )

        return StreamingConversationalRetrievalChain.from_llm(*args, **kwargs)

    def normalize_metadata_value(self, value: Any) -> Any:
        from components.agents.infrastructure.adapters.langchain.chains.retrieval import (
            normalize_metadata_value as _normalize,
        )

        return _normalize(value)

    def has_indexed_chunks(self, *args, **kwargs) -> bool:
        from components.agents.infrastructure.adapters.langchain.chains.retrieval import (
            has_indexed_chunks as _has_indexed_chunks,
        )

        return _has_indexed_chunks(*args, **kwargs)


_default = RetrievalChainProvider()


def get_retrieval_chain_provider() -> RetrievalChainProvider:
    """Return the default provider — composition root for the agents
    retrieval-chain adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
