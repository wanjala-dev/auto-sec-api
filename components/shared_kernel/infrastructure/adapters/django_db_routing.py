"""Tenant-aware DB alias resolution.

Django's router lives behind this infrastructure adapter so the application
layer can resolve the connection a model writes to (needed to scope a
``transaction.atomic(using=...)`` around a tenant-routed ``select_for_update``)
without importing Django itself — keeping ``application`` framework-free.
"""
from __future__ import annotations


def db_alias_for_write(model) -> str:
    """Return the DB alias ``model`` writes to under the active router.

    Under ``TenantRouter`` this is the current request/task tenant DB; falls
    back to ``"default"`` when no router resolves one.
    """
    from django.db import router

    return router.db_for_write(model) or "default"
