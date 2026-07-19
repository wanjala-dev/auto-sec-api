"""Security domains — the generalized 'sector' concept for auto-sec.

A **domain** is an area of security a workspace operates across: Cloud,
Endpoint, Network, Identity, Application, Data, etc. This is the renamed and
generalized successor to the nonprofit 'sector' relation the fork stripped —
kept because the product scales across different security domains (a workspace
can span several). A workspace links to domains via ``Workspace.domains``.
"""

from django.db import models


class Domain(models.Model):
    slug = models.SlugField(primary_key=True, max_length=50)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=120, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return f"{self.slug} ({self.name})"
