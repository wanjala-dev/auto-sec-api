"""Generic ``m2m_changed`` bridge for Tier 2 #8.

Wires ONE through-table's ``m2m_changed`` signal to ONE handler.
Five registrations land in
``WorkspaceIndexSignalProvider._register_workspace_m2m_bridges`` —
one each for Workspace.workspace_categories / workspace_subcategories
/ tags / operations / contribution_means — so the workspace snapshot
catches up when a category is added to or removed from a workspace.

Errors are swallowed at the receiver for the same reason as the other
knowledge bridges: a signal handler that raises would abort the
caller's save transaction.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #8.
"""
from __future__ import annotations

import logging
from typing import Type

from django.db.models import Model
from django.db.models.signals import m2m_changed

logger = logging.getLogger(__name__)


class DjangoWorkspaceM2mReindexSignalBridge:
    """Registers a single ``m2m_changed`` handler for one through model."""

    def __init__(
        self,
        *,
        through: Type[Model],
        dispatch_uid: str,
        m2m_label: str,
    ) -> None:
        self._through = through
        self._dispatch_uid = dispatch_uid
        self._m2m_label = m2m_label

    def register(self, *, handler) -> None:
        m2m_changed.connect(
            self._build_receiver(handler=handler),
            sender=self._through,
            weak=False,
            dispatch_uid=self._dispatch_uid,
        )
        logger.debug(
            "knowledge: registered workspace M2M reindex bridge "
            "through=%s dispatch_uid=%s",
            self._through.__name__,
            self._dispatch_uid,
        )

    def _build_receiver(self, *, handler):
        m2m_label = self._m2m_label

        def receiver(
            sender, instance, action, reverse, pk_set, **kwargs
        ):  # noqa: ARG001
            try:
                handler.execute(
                    action=action,
                    instance=instance,
                    pk_set=pk_set,
                    reverse=reverse,
                )
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "knowledge: workspace M2M reindex bridge handler "
                    "failed m2m=%s through=%s action=%s",
                    m2m_label,
                    sender.__name__,
                    action,
                )

        return receiver
