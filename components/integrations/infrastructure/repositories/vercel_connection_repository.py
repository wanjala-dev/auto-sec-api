"""Repository for VercelConnection (ADR 0021 D2) — the ONLY ORM slot for the
per-workspace Vercel connection catalog. Controllers/services never touch
persistence directly. Mirrors VcsConnectionRepository.
"""

from __future__ import annotations

from django.utils import timezone

from infrastructure.persistence.integrations.models import VercelConnection


class VercelConnectionRepository:
    """ORM access for a workspace's linked Vercel teams."""

    def list_for_workspace(self, workspace_id) -> list[VercelConnection]:
        return list(VercelConnection.objects.filter(workspace_id=workspace_id).order_by("created_at"))

    def get(self, workspace_id, connection_id) -> VercelConnection | None:
        return VercelConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()

    def create(
        self,
        *,
        workspace_id,
        name: str,
        team_id: str,
        team_slug: str,
        token_ciphertext: str,
        created_by=None,
        status: str = VercelConnection.Status.CONNECTED,
    ) -> VercelConnection:
        return VercelConnection.objects.create(
            workspace_id=workspace_id,
            name=name,
            team_id=team_id or "",
            team_slug=team_slug or "",
            token_ciphertext=token_ciphertext or "",
            created_by=created_by,
            status=status,
        )

    def update(
        self,
        connection: VercelConnection,
        *,
        name: str | None = None,
        team_id: str | None = None,
        team_slug: str | None = None,
        status: str | None = None,
        token_ciphertext: str | None = None,
    ) -> VercelConnection:
        """Partial update — only fields explicitly provided are written."""
        changed: list[str] = []
        if name is not None and name != connection.name:
            connection.name = name
            changed.append("name")
        if team_id is not None and team_id != connection.team_id:
            connection.team_id = team_id
            changed.append("team_id")
        if team_slug is not None and team_slug != connection.team_slug:
            connection.team_slug = team_slug
            changed.append("team_slug")
        if status is not None and status != connection.status:
            connection.status = status
            changed.append("status")
        if token_ciphertext is not None and token_ciphertext != connection.token_ciphertext:
            connection.token_ciphertext = token_ciphertext
            # A replaced token's recorded expiry belongs to the OLD token — clear it
            # so a stale date can't nag (verify() re-records the new one).
            connection.token_expires_at = None
            changed.extend(["token_ciphertext", "token_expires_at"])
        if changed:
            connection.save(update_fields=[*changed, "updated_at"])
        return connection

    def record_team(
        self,
        connection: VercelConnection,
        *,
        team_id: str,
        team_slug: str,
        team_name: str,
        token_expires_at=None,
    ) -> VercelConnection:
        """Record the canonical team trio (+ token expiry) resolved by verify()."""
        connection.team_id = team_id or connection.team_id
        connection.team_slug = team_slug or connection.team_slug
        connection.team_name = team_name or connection.team_name
        connection.token_expires_at = token_expires_at
        connection.save(update_fields=["team_id", "team_slug", "team_name", "token_expires_at", "updated_at"])
        return connection

    def mark_verified(self, connection: VercelConnection) -> VercelConnection:
        connection.status = VercelConnection.Status.CONNECTED
        connection.last_verified_at = timezone.now()
        connection.last_error = ""
        connection.save(update_fields=["status", "last_verified_at", "last_error", "updated_at"])
        return connection

    def mark_error(self, connection: VercelConnection, message: str) -> VercelConnection:
        connection.status = VercelConnection.Status.ERROR
        connection.last_error = (message or "")[:2000]
        connection.save(update_fields=["status", "last_error", "updated_at"])
        return connection

    def delete(self, connection: VercelConnection) -> None:
        connection.delete()
