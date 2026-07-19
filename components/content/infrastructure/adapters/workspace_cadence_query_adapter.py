"""Adapter: reads newsletter cadence settings from WorkspacePreference.

Implements ``WorkspaceCadenceQueryPort`` declared by
``DispatchScheduledNewslettersUseCase``. Keys off the new
``newsletter_frequency`` preference (alongside the existing
``financial_report_frequency``).
"""

from __future__ import annotations

import datetime
import logging
from typing import Sequence
from uuid import UUID

from components.content.domain.enums import NewsletterCadence

logger = logging.getLogger(__name__)


NEWSLETTER_FREQUENCY_KEY = "newsletter_frequency"


def _is_due(cadence: str, now: datetime.datetime) -> bool:
    """Determine whether a workspace with ``cadence`` should fire today.

    Weekly: Monday only (UTC). Biweekly: every other Monday based on ISO
    week-number parity. Monthly: on the 1st (UTC). The dispatch use case
    is itself idempotent via ``GenerateNewsletterUseCase.find_for_period``
    so a duplicate dispatch in the same period is a safe no-op, but the
    weekly/monthly gating keeps Beat noise low.
    """

    if cadence == NewsletterCadence.WEEKLY:
        return now.weekday() == 0  # Monday
    if cadence == NewsletterCadence.BIWEEKLY:
        return now.weekday() == 0 and now.isocalendar().week % 2 == 1
    if cadence == NewsletterCadence.MONTHLY:
        return now.day == 1
    return False


class WorkspaceCadenceQueryAdapter:
    def list_workspaces_due(
        self, *, now: datetime.datetime
    ) -> Sequence[tuple[UUID, str]]:
        from infrastructure.persistence.notifications.userpreferences.models import (
            WorkspacePreference,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        due: list[tuple[UUID, str]] = []
        eligible_workspace_ids: dict[UUID, str] = {}

        for pref in WorkspacePreference.objects.only(
            "workspace_id", "settings"
        ).iterator(chunk_size=200):
            try:
                settings_dict = pref.get_settings()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "newsletter cadence read failed workspace_id=%s",
                    pref.workspace_id,
                )
                continue
            cadence = settings_dict.get(NEWSLETTER_FREQUENCY_KEY)
            if cadence in NewsletterCadence._ALL and cadence != NewsletterCadence.NONE:
                if _is_due(cadence, now):
                    eligible_workspace_ids[pref.workspace_id] = cadence

        if not eligible_workspace_ids:
            return []

        for workspace in Workspace.objects.filter(
            id__in=eligible_workspace_ids.keys(),
            is_active=True,
        ).iterator(chunk_size=200):
            due.append((workspace.id, eligible_workspace_ids[workspace.id]))

        return due
