"""Repository for VcsConnection (ADR 0010 Phase 3) — the ONLY ORM slot for the
per-workspace VCS connection catalog. Controllers/services never touch persistence
directly. Mirrors LogSourceRepository.
"""

from __future__ import annotations

from django.utils import timezone

from infrastructure.persistence.integrations.models import VcsConnection


class VcsConnectionRepository:
    """ORM access for a workspace's linked VCS connections (GitHub/GitLab/Bitbucket)."""

    def list_for_workspace(self, workspace_id) -> list[VcsConnection]:
        return list(VcsConnection.objects.filter(workspace_id=workspace_id).order_by("provider", "created_at"))

    def get(self, workspace_id, connection_id) -> VcsConnection | None:
        return VcsConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()

    def create(
        self,
        *,
        workspace_id,
        provider: str,
        name: str,
        repo_allowlist: list,
        base_url: str,
        token_ciphertext: str,
        repo_root: str = "",
        commit_identity: str = VcsConnection.CommitIdentity.PAT_OWNER,
        commit_author_name: str = "",
        commit_author_email: str = "",
        status: str = VcsConnection.Status.CONNECTED,
    ) -> VcsConnection:
        return VcsConnection.objects.create(
            workspace_id=workspace_id,
            provider=provider,
            name=name,
            repo_allowlist=repo_allowlist or [],
            base_url=base_url or "",
            repo_root=repo_root or "",
            commit_identity=commit_identity or VcsConnection.CommitIdentity.PAT_OWNER,
            commit_author_name=commit_author_name or "",
            commit_author_email=commit_author_email or "",
            token_ciphertext=token_ciphertext or "",
            status=status,
        )

    def update(
        self,
        connection: VcsConnection,
        *,
        name: str | None = None,
        repo_allowlist: list | None = None,
        base_url: str | None = None,
        repo_root: str | None = None,
        commit_identity: str | None = None,
        commit_author_name: str | None = None,
        commit_author_email: str | None = None,
        status: str | None = None,
        token_ciphertext: str | None = None,
    ) -> VcsConnection:
        """Partial update — only fields explicitly provided are written."""
        changed: list[str] = []
        if name is not None and name != connection.name:
            connection.name = name
            changed.append("name")
        if repo_allowlist is not None and repo_allowlist != connection.repo_allowlist:
            connection.repo_allowlist = repo_allowlist
            changed.append("repo_allowlist")
        if base_url is not None and base_url != connection.base_url:
            connection.base_url = base_url
            changed.append("base_url")
        if repo_root is not None and repo_root != connection.repo_root:
            connection.repo_root = repo_root
            changed.append("repo_root")
        if commit_identity is not None and commit_identity != connection.commit_identity:
            connection.commit_identity = commit_identity
            changed.append("commit_identity")
        if commit_author_name is not None and commit_author_name != connection.commit_author_name:
            connection.commit_author_name = commit_author_name
            changed.append("commit_author_name")
        if commit_author_email is not None and commit_author_email != connection.commit_author_email:
            connection.commit_author_email = commit_author_email
            changed.append("commit_author_email")
        if status is not None and status != connection.status:
            connection.status = status
            changed.append("status")
        if token_ciphertext is not None and token_ciphertext != connection.token_ciphertext:
            connection.token_ciphertext = token_ciphertext
            changed.append("token_ciphertext")
        if changed:
            connection.save(update_fields=[*changed, "updated_at"])
        return connection

    def mark_verified(self, connection: VcsConnection) -> VcsConnection:
        connection.status = VcsConnection.Status.CONNECTED
        connection.last_verified_at = timezone.now()
        connection.last_error = ""
        connection.save(update_fields=["status", "last_verified_at", "last_error", "updated_at"])
        return connection

    def mark_error(self, connection: VcsConnection, message: str) -> VcsConnection:
        connection.status = VcsConnection.Status.ERROR
        connection.last_error = (message or "")[:2000]
        connection.save(update_fields=["status", "last_error", "updated_at"])
        return connection

    def delete(self, connection: VcsConnection) -> None:
        connection.delete()
