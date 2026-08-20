"""Reusable organization-related agent tools."""

from __future__ import annotations

import json
import uuid
from typing import Any

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


def _coerce_payload(payload: Any) -> dict[str, Any]:
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
    from components.agents.application.providers.agent_tagging_provider import AgentTaggingProvider
    from infrastructure.persistence.workspaces.models import SubCategory, Workspace, WorkspaceCategory

    try:
        data = _coerce_payload(organization_data)
        name = (data.get("name") or "").strip()
        if not name:
            return "name is required to create an organization."

        workspace = Workspace.objects.create(
            workspace_name=name,
            workspace_story=data.get("story", ""),
            privacy=data.get("privacy", "public"),
            status="active",
            workspace_owner_id=getattr(agent, "user_id", None),
        )

        for category_name in data.get("categories", []):
            category, _ = WorkspaceCategory.objects.get_or_create(name=category_name)
            workspace.workspace_categories.add(category)

        for subcategory_name in data.get("subcategories", []):
            subcategory, _ = SubCategory.objects.get_or_create(
                name=subcategory_name,
                category=workspace.workspace_categories.first() if workspace.workspace_categories.exists() else None,
            )
            workspace.workspace_subcategories.add(subcategory)

        tag_store = AgentTaggingProvider.build_tag_vocabulary_port()
        for tag_name in data.get("tags", []):
            workspace.tags.add(tag_store.get_or_create(workspace.id, tag_name).id)

        workspace.save()
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating organization: {exc}"

    categories = ", ".join(cat.name for cat in workspace.workspace_categories.all()) or "None"
    tags = ", ".join(tag.name for tag in workspace.tags.all()) or "None"

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


# The one message every tool in this module returns when the run has no
# workspace bound to it. Deliberately does NOT say "identifier is required":
# the model cannot supply one any more, and inviting a retry with an id it is
# free to invent is how the 2026-05-08 hallucination cascade started.
_NO_BOUND_WORKSPACE = "This agent run is not bound to a workspace, so there is no organization to act on."


def _bound_workspace_id(agent) -> str | None:
    """The run's workspace — the ONLY tenant any tool in this module may touch.

    ADR 0031 D1. This replaced ``_resolve_org_id``, which read
    ``organization_id`` / ``workspace_id`` / ``id`` out of the tool payload and
    *preferred* them over the agent's bound workspace, falling back to the agent
    only when the model supplied nothing parseable. That made the model the
    authority on which tenant a workspace tool acted on, across eleven tools —
    five of which write.

    The docstring it replaced was not careless: it cited a real incident and
    solved a real problem (the LLM omitting the id, so the tool defaulted to the
    agent's workspace). Under D1 that problem does not exist, because the model
    is never asked for the id and the framework strips it if the model supplies
    one anyway — see ``application/policies/tool_tenancy.py``.

    ``agent.workspace_id`` is bound when the run is created from the
    authenticated request. ``_coerce_uuid`` still guards it so a test double or
    a half-built agent carrying ``None`` produces a clean refusal rather than
    ``Workspace.objects.get(id=None)``.
    """
    return _coerce_uuid(getattr(agent, "workspace_id", None))


def get_organization_info(agent, organization_identifier: Any = None) -> str:
    """Describe the run's bound workspace.

    ``organization_identifier`` is accepted and ignored. It is retained only so
    a stored ``custom_profile.tool_whitelist`` config and any in-flight call
    that still passes one keeps working (ADR 0031 D8 — schemas grow additively,
    and a required-arg change is a new tool).

    Previously this resolved the argument by name across **every** workspace
    row: ``Workspace.objects.filter(workspace_name__iexact=identifier)``, then
    ``__icontains``. That was not merely a tenancy-preference bug like
    ``_resolve_org_id`` — it was an unscoped read that rendered another tenant's
    name, story, owner username and follower list back to the model, and a
    membership oracle for any workspace name the model cared to guess.
    """
    identifier = _bound_workspace_id(agent)
    if not identifier:
        return _NO_BOUND_WORKSPACE

    org, error = _fetch_workspace(identifier)
    if error:
        return error

    followers = org.followers.all()
    follower_names = ", ".join(follower.username for follower in followers) or "None"
    categories = ", ".join(cat.name for cat in org.workspace_categories.all()) or "None"
    subcategories = ", ".join(sub.name for sub in org.workspace_subcategories.all()) or "None"
    tags = ", ".join(tag.name for tag in org.tags.all()) or "None"

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
        org_id = _bound_workspace_id(agent)
        if not org_id:
            return _NO_BOUND_WORKSPACE
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        field = data.get("field")
        if not field:
            return "field is required (e.g. 'workspace_name', 'workspace_story', 'privacy')."
        new_value = data.get("new_value")
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
        org_id = _bound_workspace_id(agent)
        if not org_id:
            return _NO_BOUND_WORKSPACE
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = (data.get("action") or "").strip().lower()
        if not action:
            return "action is required ('add' or 'remove')."
        if action not in {"add", "remove"}:
            return f"Invalid action {action!r}. Use 'add' or 'remove'."
        user_id = data.get("user_id")
        if not user_id:
            return "user_id is required."

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except (User.DoesNotExist, ValidationError, ValueError):
            return f"User {user_id!r} not found."

        if action == "add":
            org.followers.add(user)
            return f"Added {user.username} to organization '{org.workspace_name}' team"
        org.followers.remove(user)
        return f"Removed {user.username} from organization '{org.workspace_name}' team"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing organization team: {exc}"


def get_organization_analytics(agent, analytics_params: Any = None) -> str:
    """Analytics for the run's bound workspace.

    The queryset starts scoped. It used to start as ``Workspace.objects.all()``
    and narrow *only if* an id resolved, so a run whose agent carried no
    ``workspace_id`` — a half-built agent, a test double, a background principal
    — reported counts and follower totals aggregated across **every tenant in
    the database**. The unscoped queryset was the bug; the filter was the
    mitigation. Now there is no unscoped queryset to mitigate.
    """
    from infrastructure.persistence.workspaces.models import Workspace

    org_id = _bound_workspace_id(agent)
    if not org_id:
        return _NO_BOUND_WORKSPACE

    organizations = Workspace.objects.filter(id=org_id)

    total = organizations.count()
    active = organizations.filter(status="active").count()
    verified = organizations.filter(is_verified=True).count()
    public = organizations.filter(privacy="public").count()
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
    from infrastructure.persistence.workspaces.models import SubCategory, WorkspaceCategory

    data = _coerce_payload(category_data)
    org_id = _bound_workspace_id(agent)
    if not org_id:
        return _NO_BOUND_WORKSPACE
    org, error = _fetch_workspace(org_id)
    if error:
        return error

    for category_name in data.get("categories", []):
        category, _ = WorkspaceCategory.objects.get_or_create(name=category_name)
        org.workspace_categories.add(category)

    for subcategory_name in data.get("subcategories", []):
        subcategory, _ = SubCategory.objects.get_or_create(
            name=subcategory_name,
            category=org.workspace_categories.first() if org.workspace_categories.exists() else None,
        )
        org.workspace_subcategories.add(subcategory)

    org.save()
    categories = ", ".join(cat.name for cat in org.workspace_categories.all()) or "None"
    subcategories = ", ".join(sub.name for sub in org.workspace_subcategories.all()) or "None"

    return (
        "Categories Updated:\n"
        f"Organization: {org.workspace_name}\n"
        f"Categories: {categories}\n"
        f"Subcategories: {subcategories}"
    )


def manage_organization_tags(agent, tag_data: Any) -> str:
    """Manage organization tags."""
    from components.agents.application.providers.agent_tagging_provider import AgentTaggingProvider

    try:
        data = _coerce_payload(tag_data)
        org_id = _bound_workspace_id(agent)
        if not org_id:
            return _NO_BOUND_WORKSPACE
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = data.get("action", "add")
        tags = data.get("tags") or []
        if not tags:
            return "tags is required (a list of tag names)."

        tag_store = AgentTaggingProvider.build_tag_vocabulary_port()
        for tag_name in tags:
            # Scoped to THIS workspace: creating a tag here can no longer put a
            # row in another tenant's vocabulary.
            tag = tag_store.get_or_create(org.id, tag_name)
            if action == "add":
                org.tags.add(tag.id)
            elif action == "remove":
                org.tags.remove(tag.id)

        org.save()
        current_tags = ", ".join(tag.name for tag in org.tags.all()) or "None"

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
    """List followers for the run's bound workspace.

    ``organization_id`` is accepted and ignored (ADR 0031 D1/D8 — the parameter
    stays so an in-flight call still binds, but nothing reads it). The coercion
    that used to turn it into a payload was deleted rather than left dangling:
    an unused parse of an argument the model controls is the shape someone
    re-wires later.
    """
    org_id = _bound_workspace_id(agent)
    if not org_id:
        return _NO_BOUND_WORKSPACE
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
                joined=follower.date_joined.strftime("%Y-%m-%d"),
            )
        )
    return "".join(lines)


def manage_organization_privacy(agent, privacy_data: Any) -> str:
    """Adjust organization privacy."""
    try:
        data = _coerce_payload(privacy_data)
        org_id = _bound_workspace_id(agent)
        if not org_id:
            return _NO_BOUND_WORKSPACE
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        privacy_level = (data.get("privacy_level") or "").strip().lower()
        if not privacy_level:
            return "privacy_level is required ('public' or 'private')."
        if privacy_level not in {"public", "private"}:
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
    """List operations for the run's bound workspace.

    ``organization_id`` is accepted and ignored — see
    ``get_organization_followers``. This is the exact tool from the 2026-05-08
    incident, where the model passed the literal string ``"None"`` here; it can
    now pass anything at all and the tenant does not move.
    """
    org_id = _bound_workspace_id(agent)
    if not org_id:
        return _NO_BOUND_WORKSPACE
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
                status="Completed" if operation.checked else "Pending",
                description=operation.text or "No description",
            )
        )
    return "".join(lines)


def manage_organization_operations(agent, operations_data: Any) -> str:
    """Add or remove organization operations."""
    from infrastructure.persistence.workspaces.models import WorkspaceOperations

    try:
        data = _coerce_payload(operations_data)
        org_id = _bound_workspace_id(agent)
        if not org_id:
            return _NO_BOUND_WORKSPACE
        org, error = _fetch_workspace(org_id)
        if error:
            return error
        action = data.get("action", "add")
        operations = data.get("operations") or []
        if not operations:
            return "operations is required (a list of operation names)."

        for operation_name in operations:
            operation, _ = WorkspaceOperations.objects.get_or_create(name=operation_name)
            if action == "add":
                org.operations.add(operation)
            elif action == "remove":
                org.operations.remove(operation)

        org.save()
        current_operations = ", ".join(op.name for op in org.operations.all()) or "None"

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
    return "Organization PDF reports are not available in this deployment."


def check_organization_permissions(agent, permission_data: Any) -> str:
    """Check a user's access to the run's bound workspace.

    The organization is always the bound workspace. ``user_id`` is still read
    from the payload — it is not a tenancy key and answering "can user X access
    this workspace" is the tool's whole purpose — but the *workspace* the answer
    is about is no longer the model's to choose. Before this change a run bound
    to workspace A could ask about workspace B and be told, correctly for B,
    "User has full organization access (organization owner)".
    """
    from components.agents.application.facades.agent_permissions_facade import ai_can

    data = _coerce_payload(permission_data)
    user_id = str(data.get("user_id") or getattr(agent, "user_id", "") or "")
    if not user_id:
        return "User identifier is required."
    organization_id = _bound_workspace_id(agent)
    if not organization_id:
        return _NO_BOUND_WORKSPACE

    org, error = _fetch_workspace(organization_id)
    if error:
        return error

    if str(org.workspace_owner.id) == user_id:
        return "User has full organization access (organization owner)"
    if org.followers.filter(id=user_id).exists():
        return f"User has organization access (team member of: {org.workspace_name})"
    if org.privacy == "public":
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
