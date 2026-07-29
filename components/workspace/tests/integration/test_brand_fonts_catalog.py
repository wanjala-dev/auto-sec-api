"""Integration: the curated brand-font catalog (seed command + endpoint)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

pytestmark = [pytest.mark.django_db]


class TestSeedBrandFonts:
    def test_seed_is_idempotent(self):
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        call_command("seed_brand_fonts")
        first_count = BrandFontOption.objects.count()
        assert first_count > 0

        call_command("seed_brand_fonts")
        assert BrandFontOption.objects.count() == first_count

    def test_reseed_updates_in_place_and_deactivates_removed(self):
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        # An entry that is not in the seed list gets deactivated, not deleted —
        # workspaces referencing it keep resolving until re-pointed.
        BrandFontOption.objects.create(key="legacy-font", label="Legacy", category="both", css_stack="serif")
        call_command("seed_brand_fonts")

        legacy = BrandFontOption.objects.get(key="legacy-font")
        assert legacy.active is False
        assert BrandFontOption.objects.filter(key="poppins", active=True).exists()


class TestBrandFontCatalogEndpoint:
    def test_requires_authentication(self, api_client):
        response = api_client.get("/workspaces/brand-fonts/")
        assert response.status_code in (401, 403)

    def test_lists_active_catalog(self, api_client, user_factory):
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        call_command("seed_brand_fonts")
        BrandFontOption.objects.filter(key="verdana").update(active=False)

        api_client.force_authenticate(user_factory())
        response = api_client.get("/workspaces/brand-fonts/")

        assert response.status_code == 200, response.content
        data = response.data["data"]
        keys = [entry["key"] for entry in data]
        assert "poppins" in keys
        assert "verdana" not in keys  # inactive entries hidden
        sample = next(entry for entry in data if entry["key"] == "poppins")
        assert set(sample.keys()) == {"key", "label", "category", "css_stack", "google_family"}
        assert "sans-serif" in sample["css_stack"]
