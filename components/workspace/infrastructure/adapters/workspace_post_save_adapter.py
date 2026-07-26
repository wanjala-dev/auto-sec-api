from __future__ import annotations

import logging

from django.conf import settings

from components.knowledge.application.providers.content_embedding_provider import (
    get_content_embedding_provider,
)
from components.workspace.application.ports.workspace_post_save_port import WorkspacePostSavePort

logger = logging.getLogger(__name__)


class WorkspacePostSaveAdapter(WorkspacePostSavePort):
    def enqueue_embeddings(self, *, workspace) -> None:
        if not getattr(settings, "ENABLE_WORKSPACE_EMBEDDINGS", True):
            return
        get_content_embedding_provider().enqueue_workspace_embedding(workspace.id)

    def bootstrap_defaults(self, *, workspace) -> None:
        # Budget/category/communication-channel seeding belonged to the nonprofit
        # domain and is not part of the security product's workspace core.
        return None
