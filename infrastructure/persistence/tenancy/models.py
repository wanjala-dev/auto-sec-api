"""Tenant — the subdomain → database registry (ADR 0029 D2).

The ONLY tenant-aware table in the control-plane ``default`` database. It holds
no customer data: a name, a subdomain, an isolation mode and — for dedicated
tenants — the connection alias. That emptiness is deliberate and load-bearing
(ADR 0029 D9): the moment customer-owned rows appear in ``default``, the
self-hosted tier stops being a connection-string change and becomes a data
migration out of the control plane.

``db_alias`` is stored rather than derived. A derived alias
(``f"tenant_{tenant.id}"`` over a UUID pk) cannot be typed into a settings key
or a ``migrate --database=`` flag by a person, and it has to match a
``DATABASES`` entry exactly.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from components.shared_platform.infrastructure.tenancy.context import KIND_DEDICATED, KIND_POOLED

#: Subdomains a tenant can never claim. ``app`` is the shared console; the rest
#: are infrastructure names we must keep free. Enforced in ``clean`` AND by a
#: database constraint — the registry is small and hand-edited, which is exactly
#: the kind of table where a bad row arrives via a person rather than a code path.
RESERVED_SUBDOMAINS = frozenset(
    {"app", "www", "api", "admin", "auth", "static", "cdn", "assets", "mail", "status", "localhost"}
)

ISOLATION_CHOICES = ((KIND_POOLED, "Pooled — shared database"), (KIND_DEDICATED, "Dedicated database"))


class Tenant(models.Model):
    """One customer's routing record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    #: The subdomain label — "senso" in senso.auto-sec.ai. Lowercase, no dots.
    subdomain = models.SlugField(max_length=63, unique=True)
    name = models.CharField(max_length=200)
    isolation_mode = models.CharField(max_length=16, choices=ISOLATION_CHOICES, default=KIND_POOLED)
    #: Required iff dedicated; must match a key in ``settings.DATABASES``.
    db_alias = models.CharField(max_length=100, blank=True, default="")
    #: Deactivation 404s at the middleware, before a connection is chosen — an
    #: access control rather than a flag some queryset has to remember to filter.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_tenant"
        ordering = ["subdomain"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(subdomain__in=sorted(RESERVED_SUBDOMAINS)),
                name="tenant_subdomain_not_reserved",
            ),
            # A dedicated tenant with no alias would route nowhere; a pooled one
            # with an alias is a contradiction that would quietly be ignored.
            models.CheckConstraint(
                condition=(
                    models.Q(isolation_mode=KIND_DEDICATED) & ~models.Q(db_alias="")
                    | models.Q(isolation_mode=KIND_POOLED) & models.Q(db_alias="")
                ),
                name="tenant_db_alias_matches_isolation_mode",
            ),
        ]
        indexes = [models.Index(fields=["subdomain", "is_active"], name="tenant_subdomain_active_idx")]

    def __str__(self) -> str:
        target = self.db_alias if self.isolation_mode == KIND_DEDICATED else "default (pooled)"
        return f"{self.subdomain} → {target}"

    def clean(self) -> None:
        errors = {}
        if self.subdomain and self.subdomain.lower() in RESERVED_SUBDOMAINS:
            errors["subdomain"] = f"'{self.subdomain}' is reserved."
        if self.isolation_mode == KIND_DEDICATED and not self.db_alias:
            errors["db_alias"] = "A dedicated tenant needs the alias of its database."
        if self.isolation_mode == KIND_POOLED and self.db_alias:
            errors["db_alias"] = "A pooled tenant shares 'default'; leave the alias blank."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Hostnames are case-insensitive and the lookup lowercases, so an
        # uppercase row would simply be unreachable.
        if self.subdomain:
            self.subdomain = self.subdomain.lower()
        super().save(*args, **kwargs)
