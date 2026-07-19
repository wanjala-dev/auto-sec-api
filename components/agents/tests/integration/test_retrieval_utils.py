"""Unit tests for lightweight retrieval helpers."""

import pytest
from types import SimpleNamespace

from components.agents.infrastructure.adapters.langchain.chains import retrieval


def _doc(pdf_id=None, workspace_id=None, user_id=None):
    return SimpleNamespace(metadata={
        "pdf_id": pdf_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
    })


def test_normalize_metadata_value_handles_none_and_strings():
    assert retrieval.normalize_metadata_value(None) is None
    assert retrieval.normalize_metadata_value(123) == "123"
    assert retrieval.normalize_metadata_value("abc") == "abc"


def test_has_indexed_chunks_returns_true_on_first_match(monkeypatch):
    docs = [
        _doc(pdf_id="1", workspace_id="2", user_id="3"),
        _doc(pdf_id="x", workspace_id="y", user_id="z"),
    ]

    class FakeRetriever:
        def get_relevant_documents(self, *_args, **_kwargs):
            return docs

    retriever = FakeRetriever()

    assert retrieval.has_indexed_chunks(retriever, pdf_id="1", workspace_id="2", user_id="3") is True


def test_has_indexed_chunks_returns_false_when_no_docs(monkeypatch):
    class FakeRetriever:
        def get_relevant_documents(self, *_args, **_kwargs):
            return []

    retriever = FakeRetriever()

    assert retrieval.has_indexed_chunks(retriever, pdf_id="missing", workspace_id=None, user_id=None) is False


def test_has_indexed_chunks_handles_exceptions(monkeypatch):
    class ExplodingRetriever:
        def get_relevant_documents(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    assert retrieval.has_indexed_chunks(ExplodingRetriever(), pdf_id=None, workspace_id=None, user_id=None) is False
