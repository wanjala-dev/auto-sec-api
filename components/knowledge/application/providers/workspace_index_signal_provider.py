"""Composition root for the workspace-index signal pipeline.

Wires Django ORM signal bridges to their handlers.  Invoked from an
``AppConfig.ready()`` hook at Django startup.

Three flows:

* The original Workspace.post_save → ``EnqueueWorkspaceReindexUseCase``
  pipeline (since Tier 1).  Catches workspace identity / mission /
  taxonomy edits to direct fields.
* Tier 2 #7 — ``post_save`` on ``Recipient`` / ``Donation`` /
  ``Grant`` / ``Campaign``.  Each save debounces a per-workspace
  reindex (60s window) so the data-aware snapshot (Tier 2 #5/#6)
  stays fresh between Workspace.post_save events and the nightly
  beat.
* Tier 2 #8 — ``m2m_changed`` on Workspace's five M2M through
  tables (categories / subcategories / tags / operations /
  contribution_means).  ``ws.tags.add(tag)`` does not fire
  ``Workspace.post_save``, so without this bridge a taxonomy edit
  would live stale in the embedding until the next direct
  ``Workspace.save()``.
"""

from __future__ import annotations


class WorkspaceIndexSignalProvider:
    """Registers post_save handlers for the knowledge context."""

    def register_signal_handlers(self) -> None:
        from components.knowledge.application.use_cases.enqueue_workspace_reindex_use_case import (
            EnqueueWorkspaceReindexUseCase,
        )
        from components.knowledge.infrastructure.adapters.django_workspace_index_signal_bridge import (
            DjangoWorkspaceIndexSignalBridge,
        )

        DjangoWorkspaceIndexSignalBridge().register(
            handler=EnqueueWorkspaceReindexUseCase(),
        )

        self._register_domain_change_bridges()
        self._register_workspace_m2m_bridges()
        self._register_delete_cleanup_bridges()

    @staticmethod
    def _register_domain_change_bridges() -> None:
        """Tier 2 #7 — wire the four domain-data bridges.

        Imports are local to keep import-time light for callers that
        only need the workspace bridge (e.g. early-boot management
        commands).  Each registration uses a stable ``dispatch_uid``
        so duplicate boots are idempotent at Django's signal layer.
        """
        from components.knowledge.application.use_cases.enqueue_domain_change_reindex_use_case import (
            EnqueueDomainChangeReindexUseCase,
        )
        from components.knowledge.infrastructure.adapters.django_domain_change_reindex_signal_bridge import (
            DjangoDomainChangeReindexSignalBridge,
        )

        # Project + Team round out the coverage. The 2026-06-11 reindex
        # audit (Tier 3 #14) showed both were drifting until the
        # nightly beat — a new project landing at 10am wasn't
        # discoverable via the snapshot until 03:45 the next morning.
        # WorkspaceMembership similarly: the Tier 3 #15 ``members``
        # section reads it by name, so an add/remove was stale until
        # the next ``Workspace.save()`` or the nightly.
        from infrastructure.persistence.project.models import Project
        from infrastructure.persistence.team.models import Team

        # Grant + WorkspaceMembership live on the workspaces
        # persistence app.
        from infrastructure.persistence.workspaces.models import (
            Grant,
            WorkspaceMembership,
        )

        for sender, dispatch_uid, label in (
            (Grant, "knowledge:grant_reindex_on_save", "grant"),
            (Project, "knowledge:project_reindex_on_save", "project"),
            (Team, "knowledge:team_reindex_on_save", "team"),
            (
                WorkspaceMembership,
                "knowledge:workspace_membership_reindex_on_save",
                "workspace_membership",
            ),
        ):
            DjangoDomainChangeReindexSignalBridge(
                sender=sender,
                dispatch_uid=dispatch_uid,
                domain_label=label,
            ).register(
                handler=EnqueueDomainChangeReindexUseCase(domain_label=label),
            )

    @staticmethod
    def _register_workspace_m2m_bridges() -> None:
        """Tier 2 #8 — wire ``m2m_changed`` for each Workspace M2M field.

        Five through tables, one bridge each.  ``Workspace.tags.through``
        is the standard Django way to reach the auto-generated through
        model — works whether or not the M2M has an explicit ``through=``.
        """
        from components.knowledge.application.use_cases.enqueue_workspace_m2m_change_reindex_use_case import (
            EnqueueWorkspaceM2mChangeReindexUseCase,
        )
        from components.knowledge.infrastructure.adapters.django_workspace_m2m_reindex_signal_bridge import (
            DjangoWorkspaceM2mReindexSignalBridge,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        # Each tuple: (M2M field accessor, dispatch_uid suffix, label).
        # Pulling the through models lazily via attribute access keeps
        # this provider tolerant of model rename / removal — if a
        # future PR drops one of these M2Ms the attribute lookup
        # raises and the boot fails loudly, which is what we want.
        m2m_definitions = (
            (Workspace.workspace_categories.through, "categories", "categories"),
            (
                Workspace.workspace_subcategories.through,
                "subcategories",
                "subcategories",
            ),
            (Workspace.tags.through, "tags", "tags"),
            (Workspace.operations.through, "operations", "operations"),
            (
                Workspace.contribution_means.through,
                "contribution_means",
                "contribution_means",
            ),
        )

        for through, uid_suffix, label in m2m_definitions:
            DjangoWorkspaceM2mReindexSignalBridge(
                through=through,
                dispatch_uid=f"knowledge:workspace_{uid_suffix}_reindex_on_m2m",
                m2m_label=label,
            ).register(
                handler=EnqueueWorkspaceM2mChangeReindexUseCase(m2m_label=label),
            )

    @staticmethod
    def _register_delete_cleanup_bridges() -> None:
        """Tier 3 #14 — Workspace + Document post_delete cleanup.

        ``EmbeddingChunk`` rows do not have a Django FK to either
        Workspace or Document; ownership lives in
        ``metadata.workspace_id`` / ``metadata.document_id`` (JSON).
        Without these bridges, deleting a parent leaves every chunk
        it owned orphaned in the table — a real tenant-isolation
        bug, not just hygiene.

        Both bridges fire from ``transaction.on_commit`` so the
        chunk DELETE doesn't run if the parent delete transaction
        rolls back.
        """
        from components.knowledge.infrastructure.adapters.django_document_chunk_cleanup_signal_bridge import (
            DjangoDocumentChunkCleanupSignalBridge,
        )
        from components.knowledge.infrastructure.adapters.django_workspace_chunk_cleanup_signal_bridge import (
            DjangoWorkspaceChunkCleanupSignalBridge,
        )

        DjangoWorkspaceChunkCleanupSignalBridge.register()
        DjangoDocumentChunkCleanupSignalBridge.register()
