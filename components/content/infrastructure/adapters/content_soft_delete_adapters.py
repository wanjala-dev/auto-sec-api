"""Recycle-bin ``SoftDeletePort`` adapters for Communications artifacts
(task #29 — Henry: deleting a draft, blog, or newsletter of anything
should go to the recycle bin, never hard-delete).

Both models hide trashed rows at the DEFAULT manager (``objects``), so
trash makes the artifact vanish from every read path at once; these
adapters flip the flag via ``all_objects`` (the only code allowed to see
trashed rows) and hard-delete only on bin purge. Blogs are WritingDraft
rows (kind=blog), so the draft adapter covers them.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class _ContentArtifactSoftDeleteAdapter(SoftDeletePort):
    """Shared flag-flip mechanics; subclasses name the model + entity type."""

    _model_label = ""
    _entity_type = ""

    def _model(self):
        from django.apps import apps

        return apps.get_model(self._model_label)

    def soft_delete(self, entity_id: str) -> dict:
        obj = self._model().all_objects.get(pk=entity_id, is_deleted=False)
        snapshot = {
            "id": str(obj.pk),
            "name": str(obj.title or ""),
            "kind": self._entity_type,
            "workspace_id": str(obj.workspace_id or ""),
        }
        obj.is_deleted = True
        obj.updated_at = timezone.now()
        obj.save(update_fields=["is_deleted", "updated_at"])
        logger.info("content_artifact_trashed kind=%s id=%s", self._entity_type, entity_id)
        return snapshot

    def restore(self, entity_id: str) -> None:
        obj = self._model().all_objects.get(pk=entity_id, is_deleted=True)
        obj.is_deleted = False
        obj.updated_at = timezone.now()
        obj.save(update_fields=["is_deleted", "updated_at"])
        logger.info("content_artifact_restored kind=%s id=%s", self._entity_type, entity_id)

    def hard_delete(self, entity_id: str) -> None:
        self._model().all_objects.filter(pk=entity_id).delete()
        logger.info("content_artifact_purged kind=%s id=%s", self._entity_type, entity_id)

    def entity_type(self) -> str:
        return self._entity_type


class WritingDraftSoftDeleteAdapter(_ContentArtifactSoftDeleteAdapter):
    _model_label = "content.WritingDraft"
    _entity_type = "writing_draft"


class NewsletterSoftDeleteAdapter(_ContentArtifactSoftDeleteAdapter):
    _model_label = "content.Newsletter"
    _entity_type = "newsletter"
