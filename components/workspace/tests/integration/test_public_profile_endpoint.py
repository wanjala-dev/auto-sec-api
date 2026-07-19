"""End-to-end coverage for the public workspace profile endpoint.

This is the read half of the public donate flow:

    Anonymous visitor lands on /donate/workspace/<id>
        ↓ frontend fetches
    GET /workspaces/<id>/public/  ←  this endpoint
        ↓ renders hero + form
    Anonymous visitor submits donation
        ↓ frontend posts to
    POST /sponsorship/donations/donate/  (already public, AllowAny)

This test class is the regression guard for two invariants that are
load-bearing for nonprofit GTM:

1. The endpoint MUST work without authentication. A logged-out visitor
   who copies a shareable link must reach the donate page; if the
   endpoint regresses to ``IsAuthenticated``, the demo flow breaks.
2. The response MUST NOT leak PII. The dedicated
   ``WorkspacePublicProfileSerializer`` only exposes the brand block,
   mission, story, hero image, logo, and a fundraising stub. Owner
   email, staff roster, financial detail, and internal IDs must stay
   absent from the response shape.
"""
from __future__ import annotations

import pytest


pytestmark = [pytest.mark.django_db]


class TestWorkspacePublicProfile:
    def test_anonymous_visitor_can_load_profile(self, api_client, workspace_factory):
        # Crucial — no force_authenticate. A logged-out APIClient is
        # exactly the state of a fresh browser landing on the shared
        # link.
        workspace = workspace_factory(
            workspace_name="Literacy Seed",
            mission="Educating children across East Africa",
            workspace_story="We've placed 1,200 children in school.",
            photo_url="https://cdn.example.com/logo.png",
            cover_photo_url="https://cdn.example.com/hero.jpg",
        )

        response = api_client.get(f"/workspaces/{workspace.id}/public/")

        assert response.status_code == 200, response.content
        data = response.data
        assert data["type"] == "workspace"
        assert data["title"] == "Literacy Seed"
        assert data["subtitle"] == "Educating children across East Africa"
        assert data["description"] == "We've placed 1,200 children in school."
        assert data["logo_url"] == "https://cdn.example.com/logo.png"
        assert data["hero_image_url"] == "https://cdn.example.com/hero.jpg"
        assert data["brand"]["name"] == "Literacy Seed"
        assert data["accepts_anonymous_donations"] is True
        assert data["allows_account_creation"] is True

    def test_response_shape_does_not_leak_owner_or_internal_fields(
        self, api_client, workspace_factory
    ):
        workspace = workspace_factory()

        response = api_client.get(f"/workspaces/{workspace.id}/public/")

        assert response.status_code == 200
        data = response.data
        # PII / internal fields that MUST NOT appear in the response.
        forbidden_keys = {
            "workspace_owner",
            "owner",
            "owner_email",
            "contact_email",
            "stripe_customer_id",
            "stripe_subscription_id",
            "subscription_payment_method_id",
            "shared_user",
            "shared_body",
            "plan_status",
            "plan_end_date",
            "followers",
            "members",
        }
        for key in forbidden_keys:
            assert key not in data, (
                f"public profile leaked private field '{key}': "
                f"{data.get(key)!r}"
            )

    def test_returns_404_for_nonexistent_workspace(self, api_client):
        import uuid as _uuid

        response = api_client.get(f"/workspaces/{_uuid.uuid4()}/public/")

        assert response.status_code == 404

    def test_returns_uniform_shape_keys(self, api_client, workspace_factory):
        # The registry pattern on the frontend depends on a uniform
        # shape across workspace / event / campaign profiles. This
        # asserts the contract.
        workspace = workspace_factory()

        response = api_client.get(f"/workspaces/{workspace.id}/public/")

        assert response.status_code == 200
        required_keys = {
            "type",
            "id",
            "title",
            "subtitle",
            "description",
            "hero_image_url",
            "logo_url",
            "brand",
            "fundraising",
            "currency",
            "accepts_anonymous_donations",
            "allows_account_creation",
        }
        missing = required_keys - set(response.data.keys())
        assert not missing, f"public profile missing required keys: {missing}"
        assert set(response.data["brand"].keys()) == {"name", "logo_url"}
        assert set(response.data["fundraising"].keys()) == {
            "goal_amount",
            "raised_amount",
            "currency",
            "donor_count",
        }
