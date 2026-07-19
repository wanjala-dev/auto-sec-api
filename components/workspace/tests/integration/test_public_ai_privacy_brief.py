import pytest


pytestmark = pytest.mark.django_db


def test_public_ai_privacy_brief_endpoint_returns_reassurance_content(api_client):
    response = api_client.get("/workspaces/public/ai-privacy-brief/")

    assert response.status_code == 200
    payload = response.data
    assert payload["status"] == "success"

    data = payload["data"]
    assert "privacy_controls" in data
    assert isinstance(data["privacy_controls"], list)
    assert len(data["privacy_controls"]) >= 3

    assert "data_residency" in data
    assert "CASL" in data["casl_reassurance"]["headline"]
    assert data["last_reviewed"] == "2026-02-28"
