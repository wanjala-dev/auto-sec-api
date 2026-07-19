"""Fan-out query — the merged pending-sign-off queue for a workspace.

Asks every registered adapter for its own pending rows, merges them, and orders
them so the reviewer's attention lands where it matters: highest risk first
(RED → AMBER → GREEN), then oldest-waiting first within a band.

One adapter failing (a bad row, a transient DB error) must NOT blank the whole
queue — the offending type is logged and skipped so the reviewer still sees
every other context's pending work. This is the one legitimate log-and-continue
in the kernel (per the logging rule's bulk-loop exception).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as _tz

from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
    get_sign_off_registry,
)
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem

logger = logging.getLogger(__name__)

# Severity order for the queue: most-severe first.
_BAND_RANK: dict[RiskBand, int] = {
    RiskBand.RED: 0,
    RiskBand.AMBER: 1,
    RiskBand.GREEN: 2,
}
# Items with no created_at sort after dated ones within a band (aware max).
_UNDATED = datetime.max.replace(tzinfo=_tz.utc)


def _sort_key(item: SignOffItem):
    created = item.created_at or _UNDATED
    # Normalise naive datetimes so aware/naive never compare (would raise).
    if created.tzinfo is None:
        created = created.replace(tzinfo=_tz.utc)
    return (_BAND_RANK.get(item.risk_band, 99), created)


def list_pending_sign_offs(
    workspace_id: str,
    *,
    registry: SignOffRegistry | None = None,
) -> list[SignOffItem]:
    """Merge every adapter's pending rows for the workspace, sorted red→green
    then oldest-first."""
    registry = registry or get_sign_off_registry()
    items: list[SignOffItem] = []
    for artifact_type in registry.supported_types():
        adapter = registry.get_adapter(artifact_type)
        try:
            items.extend(adapter.list_pending(str(workspace_id)))
        except Exception:
            # A single bad adapter must not blank the whole queue.
            logger.exception(
                "sign_off.list_pending_failed artifact_type=%s workspace_id=%s",
                artifact_type,
                workspace_id,
            )
            continue
    items.sort(key=_sort_key)
    return items
