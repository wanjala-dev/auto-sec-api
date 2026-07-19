"""Reusable organization-related agent tools."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, Sequence


# LLMs routinely pass the literal strings ``"None"`` / ``"null"`` /
# ``"undefined"`` when they want to omit an argument. ``data.get(key)``
# on those is truthy, so without this filter the value sails past every
# falsiness check and lands in ``Workspace.objects.get(id=...)``, where
# Django raises ``ValidationError: "'None' is not a valid UUID"``.
# That traceback then bubbles up as the tool's response text, and the
# LLM happily narrates it back as if it were data — see the prod
# incident on 2026-05-08 where Henry asked "how many tasks are in
# progress?" and got back fabricated content lifted from the tool's
# own crash message.
_NULLISH_STRINGS = frozenset({"none", "null", "undefined", "nil", ""})


def _is_nullish(value: Any) -> bool:
    """True if *value* should be treated as 'no value' even when it
    arrives as a stringified placeholder from the LLM."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULLISH_STRINGS:
        return True
    return False


def _coerce_uuid(value: Any) -> str | None:
    """Return *value* as a UUID string if it parses, else None.

    Accepts both UUID objects and strings. Filters out the LLM's
    nullish placeholders (``"None"`` etc.) before parsing so the
    caller can fall back to a workspace default rather than hand a
    bad string to the ORM.
    """
    if _is_nullish(value):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


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
            # Treat plain text as a free-form field to avoid hard failure
            return {"text": payload}
    return {}


def create_organization(agent, organization_data: Any) -> str:
    """Create a new organization/workspace."""
    from infrastructure.persistence.workspaces.models import Workspace, WorkspaceCategory, SubCategory, Tag

    try:
        data = _coerce_payload(organization_data)
        name = (data.get('name') or '').strip()
        if not name:
            return "name is required to create an organization."

        workspace = Workspace.objects.create(
            workspace_name=name,
            workspace_story=data.get('story', ''),
            privacy=data.get('privacy', 'public'),
            status='active',
            workspace_owner_id=getattr(agent, 'user_id', None),
        )

        for category_name in data.get('categories', []):
            category, _ = WorkspaceCategory.objects.get_or_create(name=category_name)
            workspace.workspace_categories.add(category)

        for subcategory_name in data.get('subcategories', []):
            subcategory, _ = SubCategory.objects.get_or_create(
                name=subcategory_name,
                category=workspace.workspace_categories.first() if workspace.workspace_categories.exists() else None,
            )
            workspace.workspace_subcategories.add(subcategory)

        for tag_name in data.get('tags', []):
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            workspace.tags.add(tag)

        workspace.save()
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating organization: {exc}"

    categories = ', '.join(cat.name for cat in workspace.workspace_categories.all()) or 'None'
    tags = ', '.join(tag.name for tag in workspace.tags.all()) or 'None'

    return (
        "Organization Created Successfully:\n"
        f"ID: {workspace.id}\n"
        f"Name: {workspace.workspace_name}\n"
        f"Story: {workspace.workspace_story or 'No story provided'}\n"
        f"Privacy: {workspace.privacy}\n"
        f"Status: {workspace.status}\n"
        f"Categories: {categories}\n"
        f"Tags: {tags}\n"
        f"Created: {workspace.created_at.strftime('%Y-%m-%d %H:%M')}"
    )


def _fetch_workspace(org_id: str):
    """Fetch a Workspace by validated UUID string. Returns ``(workspace,
    error_message)`` — exactly one will be set.

    Catches every Django lookup failure and returns a flat error
    string. Tools then return that string verbatim instead of letting
    a traceback bubble up to the LLM, which (as the 2026-05-08
    incident showed) the model will narrate back to the user as if
    the traceback were data.
    """
    from django.core.exceptions import ValidationError
    from infrastructure.persistence.workspaces.models import Workspace

    try:
        return Workspace.objects.get(id=org_id), None
    except Workspace.DoesNotExist:
        return None, f"No organization found with id {org_id}."
    except ValidationError:
        return None, "Organization id is malformed; expected a UUID."


def _resolve_org_id(data: Dict[str, Any], agent) -> str | None:
    """Resolve ``organization_id`` from a tool payload, falling back to
    the active workspace.

    The LLM frequently fails to pass ``organization_id`` because the
    workspace context is implicit. We default to ``agent.workspace_id``
    so single-step questions like "give me an overview" work without
    the model having to invent a UUID. Explicit values still win —
    BUT ONLY if they parse as a real UUID. Strings like ``"None"`` /
    ``"null"`` / a free-form workspace name are all treated as
    "argument missing" so the caller transparently falls through to
    the agent's bound workspace instead of handing the ORM a value
    it'll reject. See the 2026-05-08 incident note in this module's
    header.
    """
    for key in ("organization_id", "workspace_id", "id"):
        candidate = _coerce_uuid(data.get(key))
        if candidate:
            return candidate
    return _coerce_uuid(getattr(agent, "workspace_id", None))


def _extract_identifier(raw: Any, agent=None) -> str:
    data = _coerce_payload(raw)
    identifier = (
        data.get('organization_identifier')
        or data.get('organization_id')
        or data.get('id')
        or data.get('text')
    )
    if not identifier and isinstance(raw, str):
        identifier = raw
    if not identifier and agent is not None:
        identifier = getattr(agent, 'workspace_id', None)
    if not identifier:
        return ''
    identifier = str(identifier).strip()
    # Strip common ASCII quotes and Unicode curly quotes
    identifier = identifier.strip("\"'“”‘’`”")
    if identifier.lower().startswith('organization_identifier'):
        _, _, identifier = identifier.partition(':')
        identifier = identifier.strip()
    return identifier.strip("\"'“”‘’`” ")


def get_organization_info(agent, organization_identifier: Any) -> str:
    """Retrieve organization information by ID or name."""
    from django.core.exceptions import ValidationError
    from infrastructure.persistence.workspaces.models import Workspace

    identifier = _extract_identifier(organization_identifier, agent)
    if not identifier:
        return "Organization identifier not provided"

    org = None
    # Try exact UUID/int ID match first; on UUIDField a non-UUID string
    # raises ValidationError rather than returning empty, so we guard.
    try:
        org = Workspace.objects.filter(id=identifier).first()
    except (ValidationError, ValueError):
        org = None
    if not org and identifier.isdigit():
        try:
            org = Workspace.objects.filter(id=int(identifier)).first()
        except (ValidationError, ValueError):
            org = None
    if not org:
        org = Workspace.objects.filter(workspace_name__iexact=identifier).first()
    if not org:
        org = Workspace.objects.filter(workspace_name__icontains=identifier).first()
    # Final fallback: when the LLM passes something we can't resolve at
    # all, default to the active workspace.  Prevents "Organization X
    # not found" when a freeform query like "Wanjala Foundation" leaks
    # in as the identifier for a workspace whose real name differs.
    if not org:
        ws_id = getattr(agent, "workspace_id", None)
        if ws_id:
            try:
                org = Workspace.objects.filter(id=ws_id).first()
            except (ValidationError, ValueError):
                org = None
    if not org:
        return f"Organization '{identifier}' not found"

    followers = org.followers.all()
    follower_names = ', '.join(follower.username for follower in followers) or 'None'
    categories = ', '.join(cat.name for cat in org.workspace_categories.all()) or 'None'
    subcategories = ', '.join(sub.name for sub in org.workspace_subcategories.all()) or 'None'
    tags = ', '.join(tag.name for tag in org.tags.all()) or 'None'

    return (
        "Organization Information:\n"
        f"Name: {org.workspace_name}\n"
        f"ID: {org.id}\n"
        f"Owner: {org.workspace_owner.username}\n"
        f"Story: {org.workspace_story or 'No story provided'}\n"
        f"Privacy: {org.privacy}\n"
        f"Status: {org.status}\n"
        f"Is Verified: {org.is_verified}\n"
        f"Is Active: {org.is_active}\n"
        f"Followers: {followers.count()} ({follower_names})\n"
        f"Categories: {categories}\n"
        f"Subcategories: {subcategories}\n"
        f"Tags: {tags}\n"
        f"Start Date: {org.start_date or 'Not set'}\n"
        f"End Date: {org.end_date or 'Not set'}\n"
        f"Created: {org.created_at.strftime('%Y-%m-%d')}\n"
        f"Last Updated: {org.updated_at.strftime('%Y-%m-%d')}"
    )


def update_organization(agent, update_data: Any) -> str:
    """Update organization fields."""
    try:
        data = _coerce_payload(update_data)
        org_id = _resolve_org_id(data, agent)
        if not org_id:
            return "Organization identifier is required."
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        field = data.get('field')
        if not field:
            return "field is required (e.g. 'workspace_name', 'workspace_story', 'privacy')."
        new_value = data.get('new_value')
        if new_value is None:
            return "new_value is required."

        if not hasattr(org, field):
            return f"Field '{field}' does not exist on organization model"

        setattr(org, field, new_value)
        org.save()

        return (
            "Organization Updated Successfully:\n"
            f"Name: {org.workspace_name}\n"
            f"Updated {field}: {new_value}\n"
            f"Last Updated: {org.updated_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating organization: {exc}"


def manage_organization_team(agent, team_data: Any) -> str:
    """Add or remove organization team members."""
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError

    try:
        data = _coerce_payload(team_data)
        org_id = _resolve_org_id(data, agent)
        if not org_id:
            return "Organization identifier is required."
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = (data.get('action') or '').strip().lower()
        if not action:
            return "action is required ('add' or 'remove')."
        if action not in {'add', 'remove'}:
            return f"Invalid action {action!r}. Use 'add' or 'remove'."
        user_id = data.get('user_id')
        if not user_id:
            return "user_id is required."

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except (User.DoesNotExist, ValidationError, ValueError):
            return f"User {user_id!r} not found."

        if action == 'add':
            org.followers.add(user)
            return f"Added {user.username} to organization '{org.workspace_name}' team"
        org.followers.remove(user)
        return f"Removed {user.username} from organization '{org.workspace_name}' team"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing organization team: {exc}"


def get_organization_analytics(agent, analytics_params: Any) -> str:
    """Generate organization analytics summary."""
    from infrastructure.persistence.workspaces.models import Workspace

    data = _coerce_payload(analytics_params)
    organizations = Workspace.objects.all()

    org_id = _resolve_org_id(data, agent)
    if org_id:
        organizations = organizations.filter(id=org_id)

    total = organizations.count()
    active = organizations.filter(status='active').count()
    verified = organizations.filter(is_verified=True).count()
    public = organizations.filter(privacy='public').count()
    total_followers = sum(org.followers.count() for org in organizations)
    avg_followers = total_followers / total if total else 0

    return (
        "Organization Analytics\n"
        f"Total Organizations: {total}\n"
        f"Active Organizations: {active}\n"
        f"Verified Organizations: {verified}\n"
        f"Public Organizations: {public}\n\n"
        "Engagement Statistics:\n"
        f"Total Followers: {total_followers}\n"
        f"Average Followers per Organization: {avg_followers:.1f}"
    )


def manage_organization_categories(agent, category_data: Any) -> str:
    """Manage organization categories and subcategories."""
    from infrastructure.persistence.workspaces.models import WorkspaceCategory, SubCategory

    data = _coerce_payload(category_data)
    org_id = _resolve_org_id(data, agent)
    if not org_id:
        return "Organization identifier is required to manage categories."
    org, error = _fetch_workspace(org_id)
    if error:
        return error

    for category_name in data.get('categories', []):
        category, _ = WorkspaceCategory.objects.get_or_create(name=category_name)
        org.workspace_categories.add(category)

    for subcategory_name in data.get('subcategories', []):
        subcategory, _ = SubCategory.objects.get_or_create(
            name=subcategory_name,
            category=org.workspace_categories.first() if org.workspace_categories.exists() else None,
        )
        org.workspace_subcategories.add(subcategory)

    org.save()
    categories = ', '.join(cat.name for cat in org.workspace_categories.all()) or 'None'
    subcategories = ', '.join(sub.name for sub in org.workspace_subcategories.all()) or 'None'

    return (
        "Categories Updated:\n"
        f"Organization: {org.workspace_name}\n"
        f"Categories: {categories}\n"
        f"Subcategories: {subcategories}"
    )


def manage_organization_tags(agent, tag_data: Any) -> str:
    """Manage organization tags."""
    from infrastructure.persistence.workspaces.models import Tag

    try:
        data = _coerce_payload(tag_data)
        org_id = _resolve_org_id(data, agent)
        if not org_id:
            return "Organization identifier is required."
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = data.get('action', 'add')
        tags = data.get('tags') or []
        if not tags:
            return "tags is required (a list of tag names)."

        for tag_name in tags:
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            if action == 'add':
                org.tags.add(tag)
            elif action == 'remove':
                org.tags.remove(tag)

        org.save()
        current_tags = ', '.join(tag.name for tag in org.tags.all()) or 'None'

        return (
            f"Tags {action.capitalize()}d:\n"
            f"Organization: {org.workspace_name}\n"
            f"Action: {action}\n"
            f"Tags: {', '.join(tags)}\n"
            f"Current Tags: {current_tags}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing organization tags: {exc}"


def get_organization_followers(agent, organization_id: Any = None) -> str:
    """List followers for an organization."""
    data = _coerce_payload(organization_id) if not isinstance(organization_id, str) else {"organization_id": organization_id}
    org_id = _resolve_org_id(data, agent)
    if not org_id:
        return "Organization identifier is required."
    org, error = _fetch_workspace(org_id)
    if error:
        return error
    followers = org.followers.all()
    if not followers:
        return f"No followers found for organization '{org.workspace_name}'"

    lines = [
        f"Organization Followers: {org.workspace_name} ({followers.count()} followers)\n",
    ]
    for follower in followers:
        lines.append(
            "• {username}\n  Email: {email}\n  Joined: {joined}\n  \n".format(
                username=follower.username,
                email=follower.email,
                joined=follower.date_joined.strftime('%Y-%m-%d'),
            )
        )
    return ''.join(lines)


def manage_organization_privacy(agent, privacy_data: Any) -> str:
    """Adjust organization privacy."""
    try:
        data = _coerce_payload(privacy_data)
        org_id = _resolve_org_id(data, agent)
        if not org_id:
            return "Organization identifier is required."
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        privacy_level = (data.get('privacy_level') or '').strip().lower()
        if not privacy_level:
            return "privacy_level is required ('public' or 'private')."
        if privacy_level not in {'public', 'private'}:
            return f"Invalid privacy level {privacy_level!r}. Use 'public' or 'private'."

        org.privacy = privacy_level
        org.save()

        return (
            "Privacy Updated:\n"
            f"Organization: {org.workspace_name}\n"
            f"Privacy Level: {org.privacy}\n"
            f"Updated: {org.updated_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing organization privacy: {exc}"


def get_organization_operations(agent, organization_id: Any = None) -> str:
    """List organization operations."""
    data = _coerce_payload(organization_id) if not isinstance(organization_id, str) else {"organization_id": organization_id}
    org_id = _resolve_org_id(data, agent)
    if not org_id:
        return "Organization identifier is required."
    org, error = _fetch_workspace(org_id)
    if error:
        return error
    operations = org.operations.all()
    if not operations:
        return f"No operations found for organization '{org.workspace_name}'"

    lines = [
        f"Organization Operations: {org.workspace_name} ({operations.count()} operations)\n\n",
    ]
    for operation in operations:
        lines.append(
            "• {name}\n  Status: {status}\n  Description: {description}\n  \n".format(
                name=operation.name,
                status='Completed' if operation.checked else 'Pending',
                description=operation.text or 'No description',
            )
        )
    return ''.join(lines)


def manage_organization_operations(agent, operations_data: Any) -> str:
    """Add or remove organization operations."""
    from infrastructure.persistence.workspaces.models import WorkspaceOperations

    try:
        data = _coerce_payload(operations_data)
        org_id = _resolve_org_id(data, agent)
        if not org_id:
            return "Organization identifier is required."
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = data.get('action', 'add')
        operations = data.get('operations') or []
        if not operations:
            return "operations is required (a list of operation names)."

        for operation_name in operations:
            operation, _ = WorkspaceOperations.objects.get_or_create(name=operation_name)
            if action == 'add':
                org.operations.add(operation)
            elif action == 'remove':
                org.operations.remove(operation)

        org.save()
        current_operations = ', '.join(op.name for op in org.operations.all()) or 'None'

        return (
            f"Operations {action.capitalize()}d:\n"
            f"Organization: {org.workspace_name}\n"
            f"Action: {action}\n"
            f"Operations: {', '.join(operations)}\n"
            f"Current Operations: {current_operations}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing organization operations: {exc}"


_REPORT_VARIANTS = ("impact", "financial", "annual", "custom")


def generate_organization_report(agent, report_params: Any) -> str:
    """Not available in the Auto-Sec fork.

    The PDF organization/impact report pipeline lives in the nonprofit
    ``components.reports`` context, which is intentionally not part of this
    security fork. The tool is kept as a graceful stub so the workspace
    agent registers with a byte-stable tool set.
    """
    return (
        "Organization PDF reports are not available in this deployment."
    )


def check_organization_permissions(agent, permission_data: Any) -> str:
    """Check a user's access to an organization."""
    from components.agents.application.facades.agent_permissions_facade import ai_can

    data = _coerce_payload(permission_data)
    user_id = str(data.get('user_id') or getattr(agent, 'user_id', '') or '')
    if not user_id:
        return "User identifier is required."
    organization_id = _resolve_org_id(data, agent)
    if not organization_id:
        return "Organization identifier is required."

    org, error = _fetch_workspace(organization_id)
    if error:
        return error

    if str(org.workspace_owner.id) == user_id:
        return "User has full organization access (organization owner)"
    if org.followers.filter(id=user_id).exists():
        return f"User has organization access (team member of: {org.workspace_name})"
    if org.privacy == 'public':
        return f"User has read-only access (public organization: {org.workspace_name})"
    if ai_can(str(org.id), user_id, action="workspace:write"):
        return "User has organization access (AI executor)"
    return f"User does not have access to organization '{org.workspace_name}'"


# ── Dead text-only report helpers removed 2026-05-09 ──
#
# ``_overview_report``, ``_engagement_report``, ``_team_report``, and
# ``_comprehensive_report`` were called by the previous text-only
# ``generate_organization_report``. The PDF-artifact rewrite above
# (Henry's "shouldn't this have triggered to create a pdf report?"
# fix) replaced that path entirely; nothing else in the codebase
# called these helpers. Per the no-shortcuts rule, dead code goes.
