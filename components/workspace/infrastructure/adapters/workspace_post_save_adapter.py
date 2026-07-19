from __future__ import annotations

import logging

from django.conf import settings

from components.knowledge.infrastructure.tasks.embedding_tasks import create_embeddings_for_workspace
from components.workspace.application.ports.workspace_post_save_port import WorkspacePostSavePort

logger = logging.getLogger(__name__)


class WorkspacePostSaveAdapter(WorkspacePostSavePort):
    def enqueue_embeddings(self, *, workspace) -> None:
        if not getattr(settings, "ENABLE_WORKSPACE_EMBEDDINGS", True):
            return
        create_embeddings_for_workspace.delay(str(workspace.id))

    def bootstrap_defaults(self, *, workspace) -> None:
        # Budget/category/communication-channel seeding belonged to the nonprofit
        # domain and is not part of the security product's workspace core.
        return None
