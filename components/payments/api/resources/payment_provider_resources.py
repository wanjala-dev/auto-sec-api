"""Output DTOs for payment provider endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentProviderResource:
    """Output DTO for payment provider detail."""
    id: str | None = None
    slug: str | None = None
    display_name: str | None = None
    provider_type: str | None = None
    description: str | None = None
    icon: str | None = None
    docs_url: str | None = None
    capabilities: list[str] | None = None
    config_template: dict | None = None
    oauth_settings: dict | None = None
    is_active: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PaymentProviderCollectionResource:
    """Output DTO for payment providers list."""
    items: list[PaymentProviderResource]
    count: int = 0
