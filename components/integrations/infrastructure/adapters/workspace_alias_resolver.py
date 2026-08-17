"""Which configured database alias holds a workspace? (tenancy skill §3d)

The payload-based half of inbound-callback tenant resolution: a GitHub setup
redirect or webhook arrives with no tenant host, so the owning database is
found by an explicit cross-alias ``.using(alias)`` scan — the
``resolve_db_alias_for_stripe_account`` shape. Explicit ``using`` deliberately
bypasses the fail-closed router: this IS the resolver the router expects at a
payload-bound entry point. Offline aliases are skipped, never fatal.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def alias_owning_workspace(workspace_id: str) -> str | None:
    """Return the db alias whose ``Workspace`` table holds ``workspace_id``,
    or ``None`` when no configured database does."""
    from django.conf import settings

    from infrastructure.persistence.workspaces.models import Workspace

    aliases = list(getattr(settings, "DATABASES", {}).keys())
    if "default" in aliases:
        aliases = ["default"] + [alias for alias in aliases if alias != "default"]
    for alias in aliases:
        try:
            if Workspace.objects.using(alias).filter(id=workspace_id).exists():
                return alias
        except Exception:  # nosec B112 — an offline alias is skipped, never fatal
            logger.warning("workspace_alias_scan_alias_unavailable alias=%s", alias)
            continue
    return None
