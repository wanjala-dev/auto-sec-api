"""One generic ``SoftDeletePort`` (recycle bin) for ANY template kind.

Parametrized by model label + entity_type + name field; resolves the model via
``apps.get_model`` so the kernel never hard-imports another context's models.
Registering a template kind's delete→bin→restore→purge is then one line in the
recycle-bin composition root — no per-kind adapter class.

Requires the model to carry ``is_deleted`` (the soft-delete flag). Kinds whose
table doesn't have it yet (writing/workflow templates) get it via the Phase-1b
``TemplateBase`` migration before they register here — see the consolidation doc.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class ConfigurableTemplateSoftDeleteAdapter(SoftDeletePort):
    def __init__(self, *, model_label: str, entity_type: str, name_field: str = "name") -> None:
        self._model_label = model_label
        self._entity_type = entity_type
        self._name_field = name_field

    def _model(self):
        from django.apps import apps

        return apps.get_model(self._model_label)

    def soft_delete(self, entity_id: str) -> dict:
        model = self._model()
        obj = model.objects.get(pk=entity_id)
        # SYSTEM templates are platform-owned and shared by every
        # workspace — only workspace-owned (user-created) templates may
        # be trashed. The gallery hides the delete affordance for system
        # rows; this guard is the enforcement (a direct API call must
        # not be able to remove a template from every tenant at once).
        # ValidationError subclasses ValueError, so the recycle-bin
        # controller's existing ``except ValueError`` mapping still
        # returns a 400 with this message.
        if getattr(obj, "workspace_id", None) is None or getattr(obj, "is_seeded", False):
            from components.shared_kernel.domain.errors import ValidationError

            raise ValidationError("System templates cannot be deleted — only templates your workspace created.")
        snapshot = {
            "id": str(obj.pk),
            "name": str(getattr(obj, self._name_field, "") or ""),
            "kind": self._entity_type,
            "workspace_id": str(getattr(obj, "workspace_id", "") or ""),
        }
        obj.is_deleted = True
        if hasattr(obj, "updated_at"):
            obj.updated_at = timezone.now()
        obj.save(update_fields=["is_deleted", "updated_at"] if hasattr(obj, "updated_at") else ["is_deleted"])
        logger.info("template_trashed kind=%s id=%s", self._entity_type, entity_id)
        return snapshot

    def restore(self, entity_id: str) -> None:
        model = self._model()
        obj = model.objects.get(pk=entity_id, is_deleted=True)
        obj.is_deleted = False
        if hasattr(obj, "updated_at"):
            obj.updated_at = timezone.now()
        obj.save(update_fields=["is_deleted", "updated_at"] if hasattr(obj, "updated_at") else ["is_deleted"])
        logger.info("template_restored kind=%s id=%s", self._entity_type, entity_id)

    def hard_delete(self, entity_id: str) -> None:
        self._model().objects.filter(pk=entity_id).delete()
        logger.info("template_purged kind=%s id=%s", self._entity_type, entity_id)

    def entity_type(self) -> str:
        return self._entity_type
