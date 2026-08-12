"""Published seam: read-only repo access for SAST scans (ADR 0019 D2/D6).

The ``code_security`` pillar reads customer code THROUGH the existing ADR 0010
consent boundary — this provider is the published entry, so the pillar never
touches integrations persistence or the secret envelope. Provider files are the
composition-root slot: the implementation (ORM reads, token decrypt, Django
``sensitive_variables`` scrubbing) lives in
``infrastructure/adapters/vcs_scan_access.py``; this façade stays framework-free.

Three operations, all fail-closed on the ``repo_allowlist``:

- ``resolve_scan_connection``  — is this repo scannable for this workspace? (the
  trigger-time gate: fast 4xx before anything is enqueued)
- ``vend_repo_read_access``    — the scan-time vend: allowlist re-check, token
  decrypt, default-branch head SHA resolution, archive URL. Returns the opaque
  credential envelope the ``OpengrepScanner`` hands to its Job (token via
  secret env, D6). Scans always run against the RESOLVED commit SHA.
- ``list_scannable_repos``     — every (repo, connection_id) the beat fan-out may
  scan for a workspace (CONNECTED connections' allowlists only).
"""

from __future__ import annotations


def resolve_scan_connection(workspace_id, repo: str, connection_id: str | None = None):
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        resolve_scan_connection as _resolve,
    )

    return _resolve(workspace_id, repo, connection_id)


def list_scannable_repos(workspace_id) -> list[tuple[str, str]]:
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        list_scannable_repos as _list,
    )

    return _list(workspace_id)


def vend_repo_read_access(*, workspace_id, repo: str, connection_id: str | None = None) -> dict | None:
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        vend_repo_read_access as _vend,
    )

    return _vend(workspace_id=workspace_id, repo=repo, connection_id=connection_id)


def read_repo_file(*, workspace_id, repo: str, path: str, ref: str = "") -> str | None:
    """Read one file from an allowlisted repo (fail closed) — the SAST advisor's
    grounding read (ADR 0019 P2). ``ref`` pins the scanned commit SHA."""
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        read_repo_file as _read,
    )

    return _read(workspace_id=workspace_id, repo=repo, path=path, ref=ref)


def list_repo_tree(*, workspace_id, repo: str, ref: str = "", limit: int = 400) -> list[str]:
    """Every file path in an allowlisted repo (fail closed), capped at ``limit``."""
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        list_repo_tree as _tree,
    )

    return _tree(workspace_id=workspace_id, repo=repo, ref=ref, limit=limit)


def search_repo(*, workspace_id, repo: str, query: str, limit: int = 20) -> list[dict]:
    """Search an allowlisted repo's code (fail closed) — how the specialist finds
    the file a fix depends on instead of inventing one."""
    from components.integrations.infrastructure.adapters.vcs_scan_access import (
        search_repo as _search,
    )

    return _search(workspace_id=workspace_id, repo=repo, query=query, limit=limit)
