"""Recycle-bin soft-delete adapter for brand assets.

Registered as ``entity_type="brand_asset"`` in the recycle-bin provider so
the standard trash → restore → purge flow (and the frontend's
TrashConfirmModal pattern) works for the brand image library. No cascades —
an asset is a leaf record. Purge best-effort deletes the stored object via the
stored ``storage_key``.
"""

from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class BrandAssetSoftDeleteAdapter(SoftDeletePort):
    def soft_delete(self, entity_id: str) -> dict:
        from django.utils import timezone

        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        asset = BrandAsset.objects.get(id=entity_id)
        snapshot = {
            "id": str(asset.id),
            "workspace_id": str(asset.workspace_id),
            "url": asset.url,
            "label": asset.label,
            "kind": asset.kind,
            "created_at": str(asset.created_at),
        }
        asset.deleted = True
        asset.updated_at = timezone.now()
        asset.save(update_fields=["deleted", "updated_at"])
        return snapshot

    def restore(self, entity_id: str) -> None:
        from django.utils import timezone

        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        asset = BrandAsset.objects.get(id=entity_id, deleted=True)
        asset.deleted = False
        asset.updated_at = timezone.now()
        asset.save(update_fields=["deleted", "updated_at"])

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        asset = BrandAsset.objects.filter(id=entity_id).first()
        if asset is None:
            return
        storage_key = asset.storage_key
        asset.delete()
        if storage_key:
            # Best-effort object cleanup — a leftover object is storage cost, not
            # a correctness problem; never fail the purge over it.
            try:
                from django.core.files.storage import default_storage

                default_storage.delete(storage_key)
            except Exception:
                logger.warning("brand_asset.purge_storage_cleanup_failed key=%s", storage_key)

    def entity_type(self) -> str:
        return "brand_asset"
