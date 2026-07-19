from types import SimpleNamespace

from components.knowledge.infrastructure.adapters.pdf_embeddings import views


def test_run_embedding_for_pdf(monkeypatch, tmp_path):
    called = {}

    def fake_pdf(**kwargs):
        called["pdf"] = kwargs
        return {"ok": True}

    monkeypatch.setattr("ai.embeddings.pdf_embeddings.create_embeddings_for_pdf", fake_pdf)
    file_obj = SimpleNamespace(file_type="pdf", file=SimpleNamespace(path=str(tmp_path / "doc.pdf")))

    result = views._run_embedding_for_file(file_obj, pdf_id="123", workspace_id="workspace-1", user_id="user-1")

    assert result == {"ok": True}
    assert called["pdf"]["pdf_id"] == "123"


def test_run_embedding_for_document(monkeypatch, tmp_path):
    called = {}

    def fake_doc(**kwargs):
        called["doc"] = kwargs
        return {"ok": True}

    monkeypatch.setattr("ai.embeddings.document_embeddings.create_embeddings_for_document", fake_doc)
    file_obj = SimpleNamespace(file_type="document", file=SimpleNamespace(path=str(tmp_path / "doc.txt")))

    result = views._run_embedding_for_file(file_obj, pdf_id="321", workspace_id="workspace-2", user_id="user-2")

    assert result == {"ok": True}
    assert called["doc"]["file_id"] == "321"


def test_run_embedding_for_file_rejects_unknown(tmp_path):
    file_obj = SimpleNamespace(file_type="image", file=SimpleNamespace(path=str(tmp_path / "img.png")))

    result = views._run_embedding_for_file(file_obj, pdf_id="1", workspace_id="s", user_id="u")

    assert result["success"] is False
