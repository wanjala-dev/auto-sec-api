"""PII-safe serializers for the public donate / public storefront flow.

These are deliberately separate from the authenticated workspace
serializers — the public surface MUST NOT leak owner email, staff
roster, internal financial detail, or any of the dozens of fields the
authenticated WorkspaceSerializer exposes. Keeping a dedicated
serializer means the public response cannot drift into leaking
private data on a future refactor that adds new fields with
``fields = '__all__'``.

The shape is intentionally uniform across all public profile
endpoints (workspace, event, campaign, recipient, future product)
so the frontend's ``PublicEntityRegistry`` can render any entity
with the same component code paths.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from rest_framework import serializers


class FundraisingSummarySerializer(serializers.Serializer):
    """Uniform fundraising progress block — applies to entities with a
    monetary goal. Workspaces don't always have one (general donations
    just go to the unrestricted bucket), so every field is nullable."""

    goal_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, read_only=True
    )
    raised_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, read_only=True
    )
    currency = serializers.CharField(read_only=True)
    donor_count = serializers.IntegerField(read_only=True, allow_null=True)


class WorkspacePublicProfileSerializer(serializers.Serializer):
    """Public workspace profile for the /donate/workspace/<id> page.

    Output shape (also documented in PUBLIC_ENTITY_SHAPE.md once the
    registry doc lands):

        {
          "type": "workspace",
          "id": "<uuid>",
          "title": "Literacy Seed",
          "subtitle": "Educating children across East Africa",  // mission
          "description": "...",        // workspace_story, markdown-safe
          "hero_image_url": "...",
          "logo_url": "...",
          "brand": { "name": "Literacy Seed", "logo_url": "..." },
          "fundraising": {goal_amount, raised_amount, currency, donor_count},
          "currency": "USD",
          "accepts_anonymous_donations": true,
          "allows_account_creation": true
        }
    """

    type = serializers.SerializerMethodField()
    id = serializers.UUIDField(read_only=True)
    title = serializers.SerializerMethodField()
    subtitle = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    hero_image_url = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    brand = serializers.SerializerMethodField()
    fundraising = serializers.SerializerMethodField()
    currency = serializers.CharField(source="default_currency", read_only=True)
    accepts_anonymous_donations = serializers.SerializerMethodField()
    allows_account_creation = serializers.SerializerMethodField()

    def get_type(self, _obj) -> str:
        return "workspace"

    def get_title(self, obj) -> str:
        return obj.workspace_name or "Untitled organization"

    def get_subtitle(self, obj) -> str:
        return obj.mission or ""

    def get_description(self, obj) -> str:
        return obj.workspace_story or ""

    def get_hero_image_url(self, obj) -> str:
        return obj.cover_photo_url or ""

    def get_logo_url(self, obj) -> str:
        return obj.photo_url or ""

    def get_brand(self, obj) -> Dict[str, Any]:
        return {
            "name": obj.workspace_name or "",
            "logo_url": obj.photo_url or "",
        }

    def get_fundraising(self, obj) -> Dict[str, Any]:
        # Workspaces don't carry an explicit fundraising goal at the
        # org level — general donations land in the unrestricted bucket.
        # Returning a populated structure with nulls keeps the response
        # shape uniform with events/campaigns so the frontend renderer
        # doesn't need entity-type-specific null-handling.
        return {
            "goal_amount": None,
            "raised_amount": None,
            "currency": obj.default_currency or "USD",
            "donor_count": None,
        }

    def get_accepts_anonymous_donations(self, _obj) -> bool:
        # Default open — orgs that want to enforce donor info can opt
        # out via a workspace preference in a future iteration.
        return True

    def get_allows_account_creation(self, _obj) -> bool:
        return True
