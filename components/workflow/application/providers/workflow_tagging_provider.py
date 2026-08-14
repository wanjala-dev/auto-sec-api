"""Composition root for the tag vocabulary the workflow engine writes to.

The ``add_tag`` / ``remove_tag`` action nodes tag the workflow's directory
contact (a ``WorkspaceMembership``). The vocabulary those tags come from is
owned by the **tagging** context, so workflow reaches it through that context's
``TagStorePort`` — never its ORM (C3: cross-context reads/writes go through a
port). Mirrors ``FindingProvider.build_tag_vocabulary_port`` (ADR 0015 D7); the
findings context does exactly this for its list filter.

Before this seam existed the action node did a global
``workspaces.Tag.objects.get_or_create(name=...)`` — one row shared by every
tenant that ever automated that tag name.
"""

from __future__ import annotations

from components.tagging.application.ports.tag_store_port import TagStorePort


class WorkflowTaggingProvider:
    @staticmethod
    def build_tag_vocabulary_port() -> TagStorePort:
        """The tagging context's workspace-scoped ``TagStorePort``."""
        from components.tagging.application.providers.tagging_provider import TaggingProvider

        return TaggingProvider.build_tag_store()
