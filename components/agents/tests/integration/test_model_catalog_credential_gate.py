"""A model may only be offered if this deployment can actually call it.

The catalogue used to be gated on ``AIModel.is_available`` alone — a flag set
by hand, checked by nothing, and wrong in both directions at once:

* every seeded model sat False, including ``gpt-4o-mini`` which was serving
  live runs, so the picker was empty and the panel reported an empty catalogue;
* and ``seed_ai_models --available`` would have set all 13 True, offering
  Anthropic / Azure / Ollama models for which no credential exists. Picking one
  would have failed at CALL time — the user discovering in production that a
  choice the product offered was never possible.

Both directions are asserted here, because fixing one and breaking the other
is the easy mistake: a gate that hides everything is as wrong as one that
promises everything.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from components.agents.infrastructure.services import provider_credentials
from infrastructure.persistence.ai.llms.models import AIModel, AIModelProvider
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def catalogue():
    """One provider we hold a key for, one we do not — both fully catalogued."""
    openai = AIModelProvider.objects.create(slug="openai", name="OpenAI")
    anthropic = AIModelProvider.objects.create(slug="anthropic", name="Anthropic")
    AIModel.objects.create(
        slug="gpt-4o-mini",
        name="GPT-4o Mini",
        provider=openai,
        model_id="gpt-4o-mini",
        is_available=True,
        input_cost_per_1k="0.00015",
        output_cost_per_1k="0.0006",
    )
    AIModel.objects.create(
        slug="claude-opus-4",
        name="Claude Opus 4",
        provider=anthropic,
        model_id="claude-opus-4-20250514",
        is_available=True,
        input_cost_per_1k="0.015",
        output_cost_per_1k="0.075",
    )
    return {"openai": openai, "anthropic": anthropic}


@pytest.fixture
def member_client(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user_factory())
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role="admin",
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _get(client):
    return client.get(reverse("agents:agent-ai-models"))


class TestOnlyCallableModelsAreOffered:
    def test_a_provider_without_a_credential_is_withheld(self, catalogue, member_client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

        response = _get(member_client)

        assert response.status_code == 200
        offered = {m["slug"] for m in response.data["models"]}
        assert "gpt-4o-mini" in offered, "a model we hold a key for must be offerable"
        assert "claude-opus-4" not in offered, "offering a model with no credential moves failure to run time"

    def test_the_withheld_provider_is_explained_not_just_absent(self, catalogue, member_client, monkeypatch):
        """An admin wondering where Claude went deserves a reason."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

        response = _get(member_client)

        withheld = {p["provider"]: p for p in response.data["unavailable_providers"]}
        assert "anthropic" in withheld
        assert "ANTHROPIC_API_KEY" in withheld["anthropic"]["reason"]
        assert withheld["anthropic"]["models_withheld"] == 1

    def test_a_credentialled_provider_appears_once_configured(self, catalogue, member_client, monkeypatch):
        """The gate must OPEN too — a permanently empty catalogue is the bug we started from."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")

        response = _get(member_client)

        offered = {m["slug"] for m in response.data["models"]}
        assert offered == {"gpt-4o-mini", "claude-opus-4"}
        assert response.data["unavailable_providers"] == []

    def test_cost_is_carried_so_the_choice_can_be_priced(self, catalogue, member_client, monkeypatch):
        """Picking a model is a spend decision; the payload must let the UI say so."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

        response = _get(member_client)

        model = next(m for m in response.data["models"] if m["slug"] == "gpt-4o-mini")
        assert model["input_cost_per_1k"] == "0.00015000"[: len(model["input_cost_per_1k"])]
        assert float(model["output_cost_per_1k"]) > 0


class TestCredentialResolution:
    def test_azure_needs_both_key_and_endpoint(self, monkeypatch):
        """A partial credential is not a credential."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
        monkeypatch.delenv("AZURE_OPENAI_API_BASE", raising=False)
        assert provider_credentials.has_credential("azure") is False

        monkeypatch.setenv("AZURE_OPENAI_API_BASE", "https://example.openai.azure.com")
        assert provider_credentials.has_credential("azure") is True

    def test_ollama_accepts_either_host_variable(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        assert provider_credentials.has_credential("ollama") is False

        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        assert provider_credentials.has_credential("ollama") is True

    def test_blank_is_not_configured(self, monkeypatch):
        """An empty env var is how a 'configured' provider silently isn't."""
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        assert provider_credentials.has_credential("openai") is False

    def test_an_unknown_provider_fails_closed(self):
        assert provider_credentials.has_credential("some-new-vendor") is False
