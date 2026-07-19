import logging

from components.agents.infrastructure.adapters.langchain.chains.traceable import TraceableChain


class _BaseSuccess:
    def __call__(self, *_args, **_kwargs):
        return {"ok": True}


class _BaseFailure:
    def __call__(self, *_args, **_kwargs):
        raise RuntimeError("boom")


class _SuccessChain(TraceableChain, _BaseSuccess):
    pass


class _FailureChain(TraceableChain, _BaseFailure):
    pass


def test_traceable_chain_logs_structured_success(caplog):
    chain = _SuccessChain(metadata={"enable_tracing": False}, trace_id="trace-success")

    with caplog.at_level(logging.INFO):
        result = chain("input")

    assert result == {"ok": True}
    record = next((r for r in caplog.records if r.message == "ai.chain.trace.success"), None)
    assert record is not None
    assert record.trace["trace_id"] == "trace-success"
    assert record.trace["status"] == "success"


def test_traceable_chain_logs_structured_error(caplog):
    chain = _FailureChain(metadata={"enable_tracing": False}, trace_id="trace-error")

    with caplog.at_level(logging.ERROR):
        try:
            chain("input")
        except RuntimeError:
            pass

    record = next((r for r in caplog.records if r.message == "ai.chain.trace.error"), None)
    assert record is not None
    assert record.trace["trace_id"] == "trace-error"
    assert record.trace["status"] == "error"
    assert record.trace["error_type"] == "RuntimeError"
