"""Composition root for the tag vocabulary the workspace agent's tools write to.

``create_organization`` and ``manage_organization_tags`` let an agent put tags on
a workspace. The vocabulary is owned by the **tagging** context, so the tools
reach it through that context's ``TagStorePort`` rather than its ORM (C3).
Mirrors ``FindingProvider.build_tag_vocabulary_port`` (ADR 0015 D7).

This matters more here than in most places: an AGENT was calling
``workspaces.Tag.objects.get_or_create(name=...)`` with no workspace argument,
so a tag an agent invented while acting for one customer became a row every
other customer shared.
"""

from __future__ import annotations

from components.tagging.application.ports.tag_store_port import TagStorePort


class AgentTaggingProvider:
    @staticmethod
    def build_tag_vocabulary_port() -> TagStorePort:
        """The tagging context's workspace-scoped ``TagStorePort``."""
        from components.tagging.application.providers.tagging_provider import TaggingProvider

        return TaggingProvider.build_tag_store()
