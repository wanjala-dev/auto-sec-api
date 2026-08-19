"""Middleware package for shared_platform context.

``tenant_middlewares`` used to live here and was star-imported from this
module. It was deleted on 2026-08-19: its ``TenantMiddleware`` was never
registered in ``MIDDLEWARE`` (the live binder is
``shared_platform.infrastructure.tenancy.middleware.TenantHostMiddleware``),
and its ``set_db_for_router()`` wrote a ``threading.local`` that the live
``TenantRouter`` — which reads a ``ContextVar`` — never consults. It looked
like a tenant binder and bound nothing. See the module docstring on
``components/shared_platform/application/providers/tenancy_scopes_provider.py``
for the sanctioned binding seams.
"""
