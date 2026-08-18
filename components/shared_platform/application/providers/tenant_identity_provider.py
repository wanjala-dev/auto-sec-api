"""Composition root for the tenant identity port."""

from __future__ import annotations

from components.shared_platform.application.ports.tenant_identity_port import TenantIdentityPort


def get_tenant_identity_port() -> TenantIdentityPort:
    from components.shared_platform.infrastructure.adapters.tenant_registry_identity_adapter import (
        TenantRegistryIdentityAdapter,
    )

    return TenantRegistryIdentityAdapter()
