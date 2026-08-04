"""Tag — the one workspace-scoped tag vocabulary (ADR 0015 D2/D3).

The canonical, tenant-scoped vocabulary every taggable entity FKs (findings first,
via ``findings.FindingTag``; assets/tasks at P3). NOT the inherited global
``workspaces.Tag`` — that fork-drift surface leaks tag vocabularies across tenants
and is being retired separately (#83); new code uses THIS model exclusively.
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ActiveTagManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Tag(models.Model):
    """One row per workspace-scoped vocabulary entry (ADR 0015 D3).

    Identity is (workspace, slug) among live rows. ``slug`` is the normalized
    ``namespace:value`` (or bare ``value``) key — the filter/API handle; ``name``
    is the display label. Platform-managed tags carry ``kind="system"``.

    ``slug`` is deliberately a ``CharField``, not a ``SlugField`` — Django's
    ``SlugField`` validator rejects ``:``, which the namespaced slug requires.
    Validation lives in the domain (``components/tagging/domain/value_objects/
    tag_slug.py``), not on the field.
    """

    KIND_USER = "user"
    KIND_SYSTEM = "system"
    KIND_CHOICES = ((KIND_USER, "User"), (KIND_SYSTEM, "System"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tag_vocabulary", db_index=False)
    name = models.CharField(max_length=64)  # display label, original casing, trimmed
    slug = models.CharField(max_length=100)  # normalized identity: "env:prod", "needs-review"
    namespace = models.CharField(max_length=32, blank=True, default="")  # "" = flat tag
    color = models.CharField(max_length=7, blank=True, default="")  # "#RRGGBB" or ""
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_USER)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    active = ActiveTagManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                condition=models.Q(is_deleted=False),
                name="uniq_tag_ws_slug_live",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "is_deleted"], name="tag_ws_deleted_idx"),
            models.Index(fields=["workspace", "namespace"], name="tag_ws_namespace_idx"),
        ]

    def __str__(self) -> str:
        return self.slug
