"""User Agent tool implementations.

All tools are scoped to the agent's current workspace — never cross-workspace
reads. ``search_workspace_members`` is the agent-friendly counterpart to the
global ``UserSearch`` REST endpoint; restricting it to workspace members
prevents an email-enumeration leak through chat.

``list_user_activity`` is the only privileged tool here — it reads the
``EntityAuditLog`` actor index for a single user and is gated with
``@requires_role("owner", "admin")`` on the agent class.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID


def _coerce_payload(payload: Any) -> Dict[str, Any]:
    """Coerce tool input into a dict. Accepts None, dict, JSON string, or raw text."""
    if payload in (None, "", {}):
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:  # pylint: disable=broad-except
            return {"query": payload}
    return {}


def _maybe_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _full_name(user) -> str:
    pieces = (user.first_name or "", user.last_name or "")
    full = " ".join(p for p in pieces if p).strip()
    return full or user.username or user.email or "(unnamed user)"


def _format_member(membership, user) -> str:
    role = membership.role or "viewer"
    persona = membership.persona or "guest"
    status = membership.status or "—"
    return (
        f"• {_full_name(user)} <{user.email or '—'}>\n"
        f"  Role: {role}  Persona: {persona}  Status: {status}\n"
    )


def list_workspace_members(agent, params: Any) -> str:
    """List active members of the current workspace.

    Optional filters: ``role`` (e.g. ``owner|admin|member|viewer``),
    ``status`` (defaults to ``active``), ``limit`` (default 50, max 200).
    """
    from infrastructure.persistence.users.models import CustomUser  # noqa: F401 (used via FK)
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    try:
        data = _coerce_payload(params)
        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Assign the agent to a workspace before listing members."
            )

        status_filter = (data.get("status") or "active").strip().lower()
        qs = (
            WorkspaceMembership.objects.filter(
                workspace_id=agent.workspace_id,
                status=status_filter,
            )
            .select_related("user")
            .order_by("-created_at" if _has_field(WorkspaceMembership, "created_at") else "id")
        )

        role = data.get("role")
        if isinstance(role, str) and role.strip():
            qs = qs.filter(role=role.strip().lower())

        limit_raw = data.get("limit")
        if isinstance(limit_raw, int) and limit_raw > 0:
            limit = min(limit_raw, 200)
        else:
            limit = 50

        rows = list(qs[:limit])
        total = qs.count()

        if total == 0:
            label = f" with role '{role}'" if isinstance(role, str) and role else ""
            return f"No {status_filter} members{label} in this workspace."

        header = (
            f"Workspace members ({total} {status_filter}"
            f"{', showing first ' + str(len(rows)) if len(rows) < total else ''}):\n\n"
        )
        body = "".join(_format_member(m, m.user) for m in rows if m.user is not None)
        return header + body
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error listing workspace members: {exc}"


def search_workspace_members(agent, params: Any) -> str:
    """Search workspace members by name or email substring.

    Scoped to the current workspace deliberately — the global ``UserSearch``
    endpoint is admin-only because it enumerates every user across the
    platform, which is not safe to expose through chat.
    """
    from django.db.models import Q

    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    try:
        data = _coerce_payload(params)
        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Assign the agent to a workspace before searching members."
            )

        query = (data.get("query") or data.get("text") or "").strip()
        if not query:
            return "Provide a search query (name or email substring)."

        qs = (
            WorkspaceMembership.objects.filter(
                workspace_id=agent.workspace_id,
                status="active",
            )
            .select_related("user")
            .filter(
                Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
            .order_by("user__email")
        )

        limit_raw = data.get("limit")
        if isinstance(limit_raw, int) and limit_raw > 0:
            limit = min(limit_raw, 50)
        else:
            limit = 10

        rows = list(qs[:limit])
        if not rows:
            return f"No workspace members match '{query}'."

        header = f"Workspace members matching '{query}' ({len(rows)} shown):\n\n"
        body = "".join(_format_member(m, m.user) for m in rows if m.user is not None)
        return header + body
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error searching workspace members: {exc}"


def get_user_profile(agent, params: Any) -> str:
    """Look up a single workspace member's profile by user_id or email.

    Returns name, email, role, persona, status, and join date — fields any
    teammate can already see in the members surface. Sensitive identity
    detail (last login IP, password reset history, etc.) is intentionally
    excluded; see ``list_user_activity`` (role-gated) for audit history.
    """
    from infrastructure.persistence.users.models import CustomUser
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    try:
        data = _coerce_payload(params)
        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Assign the agent to a workspace before retrieving a profile."
            )

        user_id = _maybe_uuid(data.get("user_id"))
        email = (data.get("email") or "").strip().lower()
        identifier = data.get("query") or data.get("identifier") or ""
        if not user_id and not email and isinstance(identifier, str) and identifier.strip():
            # Identifier might be a UUID or an email — try both.
            user_id = _maybe_uuid(identifier)
            if not user_id and "@" in identifier:
                email = identifier.strip().lower()

        if not user_id and not email:
            return "Provide a user_id (UUID) or email to look up."

        user_qs = CustomUser.objects.all()
        if user_id:
            user = user_qs.filter(id=user_id).first()
        else:
            user = user_qs.filter(email__iexact=email).first()
        if user is None:
            return "No user found with that identifier."

        membership = (
            WorkspaceMembership.objects.filter(
                workspace_id=agent.workspace_id,
                user_id=user.id,
            )
            .order_by("-created_at" if _has_field(WorkspaceMembership, "created_at") else "id")
            .first()
        )
        if membership is None:
            return (
                f"{_full_name(user)} <{user.email}> is not a member of this workspace."
            )

        joined = (
            membership.created_at.strftime("%Y-%m-%d")
            if getattr(membership, "created_at", None)
            else "unknown"
        )
        return (
            f"{_full_name(user)} <{user.email}>\n"
            f"  Role: {membership.role or 'viewer'}  "
            f"Persona: {membership.persona or 'guest'}  "
            f"Status: {membership.status or '—'}\n"
            f"  Joined workspace: {joined}\n"
            f"  User id: {user.id}\n"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error retrieving user profile: {exc}"


def list_user_activity(agent, params: Any) -> str:
    """List a user's recent audit-log entries within this workspace.

    Reads ``EntityAuditLog`` filtered by ``actor`` + ``workspace`` — the
    ``(actor, -created_at)`` index makes this cheap. Returns the most recent
    edits ordered newest-first. Gated to owner/admin at the agent layer.
    """
    from infrastructure.persistence.audit.models import EntityAuditLog
    from infrastructure.persistence.users.models import CustomUser

    try:
        data = _coerce_payload(params)
        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Assign the agent to a workspace before reading activity."
            )

        user_id = _maybe_uuid(data.get("user_id"))
        email = (data.get("email") or "").strip().lower()
        identifier = data.get("query") or data.get("identifier") or ""
        if not user_id and not email and isinstance(identifier, str) and identifier.strip():
            user_id = _maybe_uuid(identifier)
            if not user_id and "@" in identifier:
                email = identifier.strip().lower()

        if not user_id and email:
            user = CustomUser.objects.filter(email__iexact=email).first()
            if user is None:
                return "No user found with that email."
            user_id = user.id

        if not user_id:
            return "Provide a user_id (UUID) or email to look up activity."

        since = _parse_iso(data.get("since"))
        if since is None:
            # Default: last 30 days. Keeps the output bounded.
            since = datetime.now(timezone.utc) - timedelta(days=30)

        limit_raw = data.get("limit")
        if isinstance(limit_raw, int) and limit_raw > 0:
            limit = min(limit_raw, 100)
        else:
            limit = 25

        qs = (
            EntityAuditLog.objects.filter(
                actor_id=user_id,
                workspace_id=agent.workspace_id,
                created_at__gte=since,
            )
            .select_related("content_type")
            .order_by("-created_at")
        )
        rows = list(qs[:limit])
        if not rows:
            return (
                f"No audit activity for user {user_id} in this workspace since "
                f"{since.strftime('%Y-%m-%d')}."
            )

        header = (
            f"Audit activity for user {user_id} since {since.strftime('%Y-%m-%d')} "
            f"({len(rows)} entries, newest first):\n\n"
        )
        lines = [header]
        for row in rows:
            entity = (
                f"{row.content_type.app_label}.{row.content_type.model}"
                if row.content_type_id
                else "unknown"
            )
            when = row.created_at.strftime("%Y-%m-%d %H:%M")
            old = _short(row.previous_value)
            new = _short(row.new_value)
            lines.append(
                f"• {when}  {entity}[{row.object_id}].{row.field_name}\n"
                f"    {old} → {new}\n"
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error listing user activity: {exc}"


def _short(value: Any, max_len: int = 80) -> str:
    """Stringify and truncate a JSON-stored audit value for display."""
    if value is None:
        return "—"
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def _has_field(model, name: str) -> bool:
    """Best-effort check that ``model`` declares ``name`` — used so we don't
    explode if WorkspaceMembership's metadata fields are renamed in a future
    migration before this tool is updated."""
    try:
        model._meta.get_field(name)
        return True
    except Exception:  # pylint: disable=broad-except
        return False
