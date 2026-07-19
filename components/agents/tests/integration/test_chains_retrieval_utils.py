from types import SimpleNamespace

from components.agents.infrastructure.adapters.langchain.chains.retrieval import has_indexed_chunks, normalize_metadata_value


class DummyDoc:
    def __init__(self, **metadata):
        self.metadata = metadata


class DummyRetriever:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def get_relevant_documents(self, query):
        self.calls.append(query)
        return list(self.docs)


def test_normalize_metadata_value():
    assert normalize_metadata_value(123) == "123"
    assert normalize_metadata_value(None) is None


def test_has_indexed_chunks_matches_triplet():
    docs = [
        DummyDoc(pdf_id="1", workspace_id="abc", user_id="u1"),
        DummyDoc(pdf_id="2", workspace_id="abc", user_id="u2"),
    ]
    retriever = DummyRetriever(docs)

    assert has_indexed_chunks(retriever, "1", "abc", "u1")
    assert retriever.calls  # ensured a probe call occurred


def test_has_indexed_chunks_handles_missing():
    retriever = DummyRetriever([])

    assert has_indexed_chunks(retriever, "missing", "workspace", "user") is False
