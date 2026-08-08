"""Resource DTOs for the code-security REST surface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoScanResource:
    task_id: str
    repo: str
    source: str

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "repo": self.repo, "source": self.source}


@dataclass(frozen=True)
class RepoScanSnapshotResource:
    """One per-repo scan snapshot row (the HUD tile's data)."""

    id: str
    scan_run_id: str
    repo: str
    commit_sha: str
    engine_version: str
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    created_at: str

    @classmethod
    def from_model(cls, row) -> RepoScanSnapshotResource:
        from components.code_security.application.providers.snapshot_provider import utc_isoformat

        return cls(
            id=str(row.id),
            scan_run_id=str(row.scan_run_id),
            repo=row.repo,
            commit_sha=row.commit_sha,
            engine_version=row.engine_version,
            total_findings=row.total_findings,
            critical_count=row.critical_count,
            high_count=row.high_count,
            medium_count=row.medium_count,
            low_count=row.low_count,
            # Aware-UTC (USE_TZ=False deployments store naive-UTC rows) so clients
            # never parse the stamp as local time.
            created_at=utc_isoformat(row.created_at),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scan_run_id": self.scan_run_id,
            "repo": self.repo,
            "commit_sha": self.commit_sha,
            "engine_version": self.engine_version,
            "total_findings": self.total_findings,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "created_at": self.created_at,
        }
