"""
Unit tests for the langfuse 3.x TracingPort adapter.

These verify the degrade discipline (missing keys / construction failure →
unavailable / None, never a crash), the LangChain 1.x handler construction,
and the session/user attribution seams the agent runtime relies on
(``callback.session_id`` mutation + ``callback.flush()`` duck-typing in
``BaseAgent.execute``).

No network I/O is asserted — the client is pointed at a closed local port and
never flushed; langfuse 3.x buffers spans in background OTEL threads and drops
them silently, which is exactly the degrade behaviour we want under test.
"""

import logging

import pytest

# The adapter under test targets the 3.x SDK layout; skip (don't fail) when an
# older langfuse is installed so the suite stays runnable mid-migration.
pytest.importorskip("langfuse.langchain", reason="langfuse 3.x SDK required")

from langchain_core.callbacks import BaseCallbackHandler

from components.agents.application.ports.tracing_port import NullTracingAdapter
from components.agents.infrastructure.adapters.tracing import langfuse as langfuse_adapter_module
from components.agents.infrastructure.adapters.tracing.langfuse import LangfuseTracingAdapter

pytestmark = pytest.mark.unit

FAKE_PUBLIC_KEY = "pk-lf-unit-test-public"
FAKE_SECRET_KEY = "sk-lf-unit-test-secret"


@pytest.fixture
def fake_credentials(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", FAKE_PUBLIC_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", FAKE_SECRET_KEY)
    # Closed port — nothing is ever exported off-box during tests.
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


class TestDegradeDiscipline:
    def test_missing_credentials_is_unavailable(self, no_credentials):
        adapter = LangfuseTracingAdapter()

        assert adapter.is_available() is False
        assert adapter.get_langchain_callback(agent_id="a1", user_id="u1") is None
        assert adapter.trace_conversation("conv-1", "u1") is None
        assert adapter.trace_llm_call(None, "gpt-x", "hi") is None
        assert adapter.trace_retrieval(None, "q", []) is None

    def test_handler_construction_failure_returns_none_and_logs(self, fake_credentials, monkeypatch, caplog):
        adapter = LangfuseTracingAdapter()
        assert adapter.is_available() is True

        def _boom():
            raise RuntimeError("handler construction failed")

        monkeypatch.setattr(langfuse_adapter_module, "_session_aware_handler_cls", _boom)

        with caplog.at_level(logging.ERROR):
            callback = adapter.get_langchain_callback(agent_id="agent-42", user_id="u1")

        assert callback is None
        assert any("agent-42" in record.getMessage() for record in caplog.records)

    def test_secrets_never_logged(self, fake_credentials, monkeypatch, caplog):
        with caplog.at_level(logging.DEBUG):
            adapter = LangfuseTracingAdapter()
            monkeypatch.setattr(
                langfuse_adapter_module,
                "_session_aware_handler_cls",
                lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            )
            adapter.get_langchain_callback(agent_id="a1", user_id="u1")

        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert FAKE_SECRET_KEY not in joined
        assert FAKE_PUBLIC_KEY not in joined

    def test_null_adapter_contract(self):
        adapter = NullTracingAdapter()

        assert adapter.is_available() is False
        assert adapter.get_langchain_callback(agent_id="a1", user_id="u1") is None


class TestLangchainCallback:
    def test_builds_langchain_1x_compatible_handler(self, fake_credentials):
        adapter = LangfuseTracingAdapter()

        callback = adapter.get_langchain_callback(agent_id="agent-1", user_id="user-1", session_id="conv-1")

        assert callback is not None
        assert isinstance(callback, BaseCallbackHandler)
        # Seams BaseAgent.execute duck-types against:
        assert callback.session_id == "conv-1"
        assert callable(callback.flush)

    def test_session_and_user_fallback_into_trace_attributes(self, fake_credentials):
        adapter = LangfuseTracingAdapter()
        callback = adapter.get_langchain_callback(agent_id="agent-1", user_id="user-1", session_id="conv-1")

        attributes = callback._parse_langfuse_trace_attributes_from_metadata({})

        assert attributes["session_id"] == "conv-1"
        assert attributes["user_id"] == "user-1"

    def test_explicit_run_metadata_wins_over_fallback(self, fake_credentials):
        adapter = LangfuseTracingAdapter()
        callback = adapter.get_langchain_callback(agent_id="agent-1", user_id="user-1", session_id="conv-1")

        attributes = callback._parse_langfuse_trace_attributes_from_metadata(
            {"langfuse_session_id": "explicit-session", "langfuse_user_id": "explicit-user"}
        )

        assert attributes["session_id"] == "explicit-session"
        assert attributes["user_id"] == "explicit-user"

    def test_session_id_mutation_seam_updates_attribution(self, fake_credentials):
        """BaseAgent.execute reassigns callback.session_id before each run."""
        adapter = LangfuseTracingAdapter()
        callback = adapter.get_langchain_callback(agent_id="agent-1", user_id="user-1", session_id="conv-1")

        callback.session_id = "conv-2"
        attributes = callback._parse_langfuse_trace_attributes_from_metadata({})

        assert attributes["session_id"] == "conv-2"


class TestManualSpanHelpers:
    def test_trace_conversation_llm_and_retrieval_spans(self, fake_credentials):
        adapter = LangfuseTracingAdapter()

        trace = adapter.trace_conversation("conv-1", "user-1", channel="unit-test")
        assert trace is not None

        generation = adapter.trace_llm_call(trace, "gpt-test", "hello", temperature="0")
        assert generation is not None
        generation.end()

        retrieval = adapter.trace_retrieval(trace, "query", ["doc-1"], k="1")
        assert retrieval is not None
        retrieval.end()

        trace.end()

    def test_span_helpers_none_trace_is_noop(self, fake_credentials):
        adapter = LangfuseTracingAdapter()

        assert adapter.trace_llm_call(None, "gpt-test", "hello") is None
        assert adapter.trace_retrieval(None, "query", []) is None
