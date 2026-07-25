"""Signal bridge: stamp the canonical ``asset_urn`` on every ProvenanceResource.

Every writer of a ``ProvenanceResource`` (the audit/identity/ai backfill services
today, any future ingester tomorrow) goes through ``pre_save``, so this is the one
drift-proof place the canonical cross-pillar identity is derived — no writer needs to
remember to set it (the exact drift the architecture skill warns against). The URN is
derived from the immutable ``(source_system, external_ref)`` identity via
``AssetUrn.canonical`` (ADR 0004 D2).

Registered from ``infrastructure/persistence/provenance/apps.py`` ``ready()`` — never
via the ``@receiver`` decorator (per django-conventions).
"""

from __future__ import annotations

import logging

from django.db.models.signals import pre_save

logger = logging.getLogger(__name__)


def _stamp_asset_urn(sender, instance, **kwargs):
    # Derived from immutable identity fields; only fill when empty so an explicit
    # value (e.g. set by a future ingester that already knows the URN) is preserved.
    if getattr(instance, "asset_urn", ""):
        return
    from components.shared_kernel.domain.security import AssetUrn

    try:
        instance.asset_urn = AssetUrn.canonical(instance.source_system, instance.external_ref).value
    except ValueError:
        # external_ref is required by the model, so this should not happen; be
        # defensive rather than fail a save on a derived convenience column.
        logger.warning(
            "provenance_resource_asset_urn_derivation_failed id=%s source_system=%s",
            getattr(instance, "id", None),
            getattr(instance, "source_system", None),
        )


class DjangoProvenanceAssetUrnBridge:
    @staticmethod
    def register():
        from infrastructure.persistence.provenance.models import ProvenanceResource

        pre_save.connect(
            _stamp_asset_urn,
            sender=ProvenanceResource,
            dispatch_uid="provenance:resource_asset_urn",
        )
