"""ORM reads over ``RepoScanSnapshot`` — the pillar's scan-level history rows.

Driven-side repository: the ONE place the snapshot table is queried with ORM
expressions (the application-layer provider stays framework-free and delegates
here).
"""

from __future__ import annotations


def latest_snapshot_rows_by_repo(workspace_id, repos: list[str]) -> dict[str, object]:
    """The newest snapshot row per repo, in TWO queries regardless of repo count
    (max ``created_at`` per repo, then the matching rows) — never a per-repo
    query (an N+1 the CODE REPOS surfaces would pay on every 30s poll)."""
    from django.db.models import Max

    from infrastructure.persistence.code_security.models import RepoScanSnapshot

    if not repos:
        return {}
    latest = (
        RepoScanSnapshot.objects.filter(workspace_id=workspace_id, repo__in=repos)
        .values("repo")
        .annotate(latest_created_at=Max("created_at"))
    )
    latest_by_repo = {row["repo"]: row["latest_created_at"] for row in latest}
    if not latest_by_repo:
        return {}
    rows = RepoScanSnapshot.objects.filter(
        workspace_id=workspace_id,
        repo__in=latest_by_repo.keys(),
        created_at__in=set(latest_by_repo.values()),
    ).order_by("created_at")
    result: dict[str, object] = {}
    for row in rows:
        if row.created_at != latest_by_repo.get(row.repo):
            continue  # another repo's timestamp collided via created_at__in
        result[row.repo] = row
    return result
