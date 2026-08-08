"""Published seam: the scan dispatch gate + per-target scan history (owner: scanning).

Framework-free façade over ``infrastructure/services/scan_gate.py`` (provider
files are the composition-root slot). Pillars call this BEFORE ``dispatch_scan``
to enforce the anti-spam budget (ADR 0019 D3) and to read per-target scan
history (last-scanned/provenance) without touching scanning's persistence.
"""

from __future__ import annotations


def check_and_lock_dispatch(*, workspace_id, source: str, target_ref: str, cooldown_seconds: int) -> dict:
    from components.scanning.infrastructure.services.scan_gate import (
        check_and_lock_dispatch as _check,
    )

    return _check(workspace_id=workspace_id, source=source, target_ref=target_ref, cooldown_seconds=cooldown_seconds)


def release_dispatch_lock(*, workspace_id, source: str, target_ref: str) -> None:
    from components.scanning.infrastructure.services.scan_gate import (
        release_dispatch_lock as _release,
    )

    _release(workspace_id=workspace_id, source=source, target_ref=target_ref)


def latest_runs_for(workspace_id, source: str, target_refs: list[str]) -> dict[str, dict]:
    from components.scanning.infrastructure.services.scan_gate import latest_runs_for as _latest

    return _latest(workspace_id, source, target_refs)
