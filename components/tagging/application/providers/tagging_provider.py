"""Composition root for the tagging context — wires ports to adapters."""

from __future__ import annotations

from components.tagging.application.ports.tag_store_port import TagStorePort


class TaggingProvider:
    @staticmethod
    def build_tag_store() -> TagStorePort:
        """The vocabulary store — the tagging context's public data seam.

        Cross-context consumers (e.g. the findings tag/untag use case and the
        tag-filtered list read) reach the vocabulary through this port, never
        the ORM (C3)."""
        from components.tagging.infrastructure.repositories.django_tag_repository import (
            DjangoTagRepository,
        )

        return DjangoTagRepository()

    @staticmethod
    def build_create_tag_use_case():
        from components.tagging.application.use_cases.create_tag_use_case import CreateTagUseCase

        return CreateTagUseCase(store=TaggingProvider.build_tag_store())

    @staticmethod
    def build_update_tag_use_case():
        from components.tagging.application.use_cases.update_tag_use_case import UpdateTagUseCase

        return UpdateTagUseCase(store=TaggingProvider.build_tag_store())

    @staticmethod
    def build_delete_tag_use_case():
        from components.tagging.application.use_cases.delete_tag_use_case import DeleteTagUseCase

        return DeleteTagUseCase(store=TaggingProvider.build_tag_store())

    @staticmethod
    def build_list_tags_use_case():
        from components.tagging.application.use_cases.list_tags_use_case import ListTagsUseCase

        return ListTagsUseCase(store=TaggingProvider.build_tag_store())
