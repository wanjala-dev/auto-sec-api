"""Node action executors for workflow step processing.

Each function handles a specific node type's side effect:
- message: sends an email (real platform EmailSendingPort) or in-app notification
- task: creates a project task
- ai: triggers an AI agent execution
- assign: creates an assigned to-do for the contact (real ProjectService task)
- add_tag / remove_tag: tag the workflow's directory contact
- update_field: update an allow-listed field on the contact's membership/profile
- webhook: calls an external URL
- publish_event: emits a shared-kernel domain event

All executors receive (run, node, config). They:
- return an output dict on success,
- return ``{"status": "skipped", ...}`` for an intentional no-op (missing
  optional config, a filter that didn't match) — this is NOT a failure,
- **RAISE on genuine failure** so the engine marks the run FAILED and logs the
  traceback. Per the workflow constitutional rules + ``.claude/rules/logging.md``
  ("fail loudly"): an executor that swallows an exception and returns a fake
  success leaves a run that "completed" without ever sending its email. That is
  the bug this contract prevents — never catch-and-return-failed; log and raise.

Contact resolution
------------------
``run.target_id`` is a string identifier for the contact the workflow walks.
For a Teams-Directory contact (the ``contact_added`` / ``directory`` trigger,
emitted by ``components.membership``) it is the **CustomUser id**, and the
contact entity is the ``WorkspaceMembership`` row for ``(workspace, user)`` —
that is the row tag / field actions mutate. See ``_resolve_membership``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

from components.workflow.domain.errors import WorkflowActionError

logger = logging.getLogger(__name__)

# Fields an ``update_field`` node is allowed to write on the contact's
# UserProfile. Deliberately narrow: it EXCLUDES everything that controls
# identity, authentication, or authorization — id, user, email, password,
# is_staff/is_superuser/is_active (CustomUser), and role/persona/status
# (WorkspaceMembership). A workflow author can never escalate privilege or
# hijack an account through this node; only safe contact-CRM attributes that
# already live on UserProfile are writable. ``update_field`` updates the
# UserProfile of the contact (target_id = the contact's user id).
_UPDATE_FIELD_ALLOWLIST = {
    "title",  # job title / role label shown on the contact card
    "about",  # free-text bio / notes
    "address",  # mailing address line
    "city",
    "zip",
    "name",  # display name on the profile (not the auth username/email)
}


def execute_node_action(
    run: Any,
    node: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Dispatch to the appropriate node action executor.

    Returns output dict on success, None on no-op, raises on failure.
    """
    node_type = node.get("type")
    executor = _EXECUTORS.get(node_type)
    if not executor:
        return None
    return executor(run, node, config)


def _resolve_contact_user(run: Any):
    """Resolve the CustomUser the workflow targets, or None.

    ``run.target_id`` is the contact's user id for directory/contact flows.
    Returns None for group targets or when the id doesn't resolve to a user.
    """
    if run.target_type not in (None, "", "contact"):
        return None
    # Anonymous donors (donation forms, public gifts) target by EMAIL, not a
    # user id — there is no account yet. ``filter(id=<email>)`` raises
    # ValidationError ("not a valid UUID") against a UUID PK, so guard: a
    # non-UUID target simply has no contact user (callers fall back to the
    # donor email from the trigger payload).
    import uuid as _uuid

    try:
        _uuid.UUID(str(run.target_id))
    except (ValueError, TypeError, AttributeError):
        return None
    from infrastructure.persistence.users.models import CustomUser

    return CustomUser.objects.filter(id=run.target_id).first()


def _resolve_membership(run: Any):
    """Resolve the WorkspaceMembership (the directory contact) for this run.

    The directory contact is the ``(workspace, user)`` membership row; that is
    the entity tag actions mutate. Returns None if there is no matching
    membership (e.g. the user was removed, or this is a group target).
    """
    user = _resolve_contact_user(run)
    if user is None:
        return None
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return (
        WorkspaceMembership.objects.filter(
            workspace_id=run.workflow.workspace_id,
            user_id=user.id,
            is_impersonation=False,
        )
        .order_by("created_at")
        .first()
    )


def _execute_message(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Send an email (real platform mailer) or an in-app notification.

    Channels: ``email`` (default ``in_app``). ``sms`` is not yet wired and is an
    explicit no-op so a graph using it doesn't fail the run. ``config.subject`` /
    ``config.body`` are used for the message content. (The writing-template body
    rendering was removed along with the content context in this fork.)
    """
    target_id = run.target_id
    channel = config.get("channel", "in_app")  # in_app, email, sms
    subject = config.get("subject", "")
    body = config.get("body", "")
    workspace_id = str(run.workflow.workspace_id)

    if channel == "sms":
        # SMS transport is not provisioned yet — intentional no-op, not a failure.
        return {"channel": "sms", "status": "skipped", "reason": "sms not configured"}

    if channel == "email":
        return _send_email_message(run, target_id, subject, body, workspace_id)

    return _send_in_app_message(run, target_id, subject, body, workspace_id)


def _resolve_email_payload(
    run: Any,
    target_id: str,
    subject: str,
    body: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Resolve the deliverable email (recipient + subject + bodies) for a message
    node, WITHOUT sending.

    Shared by the live send path (``_send_email_message``) and the sign-off park
    path (``prepare_email_signoff``) so both agree on exactly who the email goes
    to and what it says. Returns a ``{"status": "skipped", ...}`` dict when there
    is no deliverable address (a genuine no-op), otherwise a dict carrying
    ``recipient_email``, ``subject``, ``text_body``, ``html_body`` and the
    derived ``audience`` (``internal_team`` when the recipient is a contact user
    / workspace member; ``external`` when it is an anonymous donor/subscriber
    resolved from the trigger payload — see ``SignOffTarget`` risk escalation).
    """
    user = _resolve_contact_user(run)
    recipient_email = getattr(user, "email", "") if user else ""
    # A resolved contact user is a workspace directory member -> internal_team.
    audience = "internal_team" if recipient_email else ""
    if not recipient_email:
        # The target isn't a contact user (the run targets a non-user subject):
        #   * Anonymous donor (donation form / public gift): no user row yet, but
        #     the trigger payload carries ``donor_email``.
        #   * Per-transaction subject (receipt-accountability): the run targets a
        #     TRANSACTION id, and the payload carries the expense owner's
        #     ``owner_email`` — deliver the reminder to them.
        # Prefer the explicit owner, then the donor email, so each automation
        # reaches the right person without a contact account. A payload-resolved
        # recipient is an external party (donor/subscriber) -> external.
        payload = getattr(run, "trigger_payload", None) or {}
        recipient_email = (payload.get("owner_email") or payload.get("donor_email") or "").strip()
        audience = "external" if recipient_email else ""
    if not recipient_email:
        # No deliverable address — a genuine no-op (e.g. group target or a
        # contact with no email on file), not an error that should fail the run.
        return {
            "channel": "email",
            "status": "skipped",
            "reason": "no recipient email",
            "target_id": target_id,
        }

    email_subject = subject or "Workflow notification"
    text_body = body
    html_body = ""

    return {
        "status": "resolved",
        "recipient_email": recipient_email,
        "audience": audience,
        "subject": email_subject,
        "text_body": text_body,
        "html_body": html_body,
    }


def _send_email_message(
    run: Any,
    target_id: str,
    subject: str,
    body: str,
    workspace_id: str,
) -> dict[str, Any]:
    payload = _resolve_email_payload(run, target_id, subject, body, workspace_id)
    if payload.get("status") == "skipped":
        return payload

    from components.shared_platform.application.ports.email_sending_port import EmailMessage
    from components.shared_platform.application.providers.email_adapter_provider import (
        get_email_adapter_provider,
    )

    try:
        sent = (
            get_email_adapter_provider()
            .adapter()
            .send(
                EmailMessage(
                    subject=payload["subject"],
                    to=[payload["recipient_email"]],
                    text_body=payload["text_body"],
                    html_body=payload["html_body"],
                )
            )
        )
    except Exception as exc:
        logger.exception("workflow_message_email_failed run_id=%s target_id=%s", run.id, target_id)
        raise WorkflowActionError(f"message email failed: {exc}") from exc

    if not sent:
        # The adapter returns False when the backend reports a send failure.
        raise WorkflowActionError(f"message email not delivered run_id={run.id} target_id={target_id}")

    return {"channel": "email", "status": "sent", "target_id": target_id}


def _send_in_app_message(run: Any, target_id: str, subject: str, body: str, workspace_id: str) -> dict[str, Any]:
    """Create a real Notification row for the contact (in-app channel)."""
    user = _resolve_contact_user(run)
    if user is None:
        return {
            "channel": "in_app",
            "status": "skipped",
            "reason": "target is not a contact user",
            "target_id": target_id,
        }

    from components.notifications.infrastructure.adapters.notification_service import (
        NotificationDispatcher,
    )
    from infrastructure.persistence.notifications.models import Notification
    from infrastructure.persistence.workspaces.models import Workspace

    verb = body or subject or "You have a workflow notification"
    try:
        workspace = Workspace.objects.filter(id=run.workflow.workspace_id).first()
        # Workflow notifications are system-generated; the actor is the
        # contact themselves (there is no acting user in an automated step),
        # so allow_self_notify keeps the funnel from dropping it. Delivery is
        # queued post-commit, so "sent" here means "accepted for delivery".
        NotificationDispatcher().dispatch(
            actor=user,
            workspace=workspace,
            verb=verb[:255],
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[user],
            metadata={"kind": "workflow.message", "run_id": str(run.id), "target_id": str(target_id)},
            allow_self_notify=True,
        )
    except Exception as exc:
        logger.exception("workflow_message_in_app_failed run_id=%s target_id=%s", run.id, target_id)
        raise WorkflowActionError(f"message in_app failed: {exc}") from exc

    return {"channel": "in_app", "status": "sent", "target_id": target_id}


# ---------------------------------------------------------------------------
# AI-content sign-off gate (Phase 3)
# ---------------------------------------------------------------------------
# The artifact_type a parked AI workflow-email registers under in the sign-off
# kernel (see ``WorkflowEmailSignOffAdapter``). Kept as a string here to avoid an
# infra->infra import cycle; the adapter is the source of truth for the value.
WORKFLOW_EMAIL_ARTIFACT_TYPE = "workflow_email"


def classify_email_content(config: dict[str, Any], graph: Any) -> str:
    """Classify a message node's resolved email content as ``"ai"`` or
    ``"deterministic"``.

    THE SIGNAL (documented decision). Workflow ``message`` email nodes today send
    DETERMINISTIC template emails — values substituted from the trigger event
    (``config.subject`` / ``config.body`` / a content ``WritingTemplate``). Those
    carry no fabrication risk; they were signed off when the human PUBLISHED the
    workflow. The ONLY content that must be gated is content **produced by an AI
    node at runtime**.

    There is no AI->message producer wired in the engine today (the message
    executor reads only static config + a WritingTemplate, never an upstream
    ``ai`` node's output), so this is **fail-safe scaffolding**: deterministic is
    the default, and the AI path is reachable — and gated-by-default for any
    future AI producer — via either of two structural signals:

    1. **Explicit marker** — ``config.ai_generated is True`` or
       ``config.content_source == "ai"``. A future "compose this email with AI"
       builder sets this; setting it gates the node by default.
    2. **ai->message chaining** — the node is wired to draw from an ``ai`` node:
       ``config.source_node_id`` / ``config.ai_node_id`` names a graph node of
       type ``ai``, OR the subject/body references an ``ai`` node's output via a
       ``{{steps.<ai_node_id>`` / ``{{ai`` placeholder.

    Classification is by DESIGN of the node, not by whether the ai node happened
    to run — wiring an email to AI output gates it regardless of runtime, which
    is the more fail-safe reading. Pure function: no DB, no send.
    """
    if config.get("ai_generated") is True or config.get("content_source") == "ai":
        return "ai"

    ai_node_ids = {
        nid
        for nid, node in (getattr(graph, "nodes", {}) or {}).items()
        if isinstance(node, dict) and node.get("type") == "ai"
    }
    if not ai_node_ids:
        return "deterministic"

    source_ref = config.get("source_node_id") or config.get("ai_node_id")
    if source_ref and str(source_ref) in ai_node_ids:
        return "ai"

    text = " ".join(str(config.get(key) or "") for key in ("subject", "body")).lower()
    if "{{ai" in text:
        return "ai"
    for nid in ai_node_ids:
        if f"steps.{nid}".lower() in text:
            return "ai"
    return "deterministic"


def _collect_grounding(run: Any) -> list:
    """Flatten the run's grounding corpus (trigger payload + every step output)
    into stringified leaves the FaithfulnessVerifier can check figures against.

    Empty grounding is the correct strict signal — every figure in the AI copy
    then surfaces as unverifiable.
    """
    texts: list = []
    _collect_values(getattr(run, "trigger_payload", None) or {}, texts)

    from infrastructure.persistence.workspaces.workflows.models import WorkflowStepState

    for state in WorkflowStepState.objects.filter(run=run).only("output"):
        _collect_values(state.output or {}, texts)
    return texts


def _collect_values(value: Any, sink: list) -> None:
    """Recursively flatten dict/list values into stringified leaves."""
    if isinstance(value, dict):
        for nested in value.values():
            _collect_values(nested, sink)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _collect_values(nested, sink)
    elif value is not None and not isinstance(value, bool):
        sink.append(str(value))


def prepare_email_signoff(run: Any, node: dict[str, Any], config: dict[str, Any], graph: Any) -> dict[str, Any] | None:
    """If this message node's email content is AI-derived, build the sign-off
    blob the engine parks; otherwise return ``None`` (the email sends as today).

    THE GUARD. Returning a non-None blob is the signal to the engine that this
    email must NOT auto-send — it parks pending a human sign-off instead. Returns
    ``None`` for deterministic content, for non-email channels, and when there is
    no deliverable recipient (a genuine skip the normal executor handles) — so
    deterministic template emails are entirely unaffected.

    The blob carries everything the sign-off kernel needs later (Phase 6 review
    queue): the resolved ``content`` to verify, the ``grounding`` corpus, the
    ``recipient_email`` + ``audience`` for risk banding, and ``review_state``.
    """
    if config.get("channel") != "email":
        return None
    if classify_email_content(config, graph) != "ai":
        return None

    payload = _resolve_email_payload(
        run,
        run.target_id,
        config.get("subject", ""),
        config.get("body", ""),
        str(run.workflow.workspace_id),
    )
    if payload.get("status") == "skipped":
        # No deliverable address — nothing to send, so nothing to gate. Let the
        # normal executor record the skip.
        return None

    content = payload.get("html_body") or payload.get("text_body") or ""
    return {
        "artifact_type": WORKFLOW_EMAIL_ARTIFACT_TYPE,
        "review_state": "pending",
        "node_id": node.get("id"),
        "recipient_email": payload["recipient_email"],
        "audience": payload["audience"],
        "subject": payload["subject"],
        "content": content,
        "grounding": _collect_grounding(run),
        "parked_at": timezone.now().isoformat(),
    }


def _create_project_task(
    run: Any,
    *,
    title: str,
    description: str,
    column_id: str,
    user_id: str,
    project_id: str | None,
    node_label: str,
) -> dict[str, Any]:
    """Create a real project to-do via ProjectService.

    Shared by the ``task`` and ``assign`` nodes. ``CreateTaskCommand`` requires
    a valid ``column_id`` (the board column the to-do lands in) and a
    ``user_id`` who can post to that column's team — there is no "assigned_to"
    on the command; the to-do is created by ``user_id`` on the column's board.
    """
    from components.project.application.ports.create_task_port import CreateTaskCommand
    from components.project.application.service import ProjectService

    command = CreateTaskCommand(
        title=title,
        column_id=str(column_id),
        user_id=str(user_id),
        project_id=project_id,
        workspace_id=str(run.workflow.workspace_id),
        description=description,
        source_type="workflow",
        metadata={
            "workflow_id": str(run.workflow.id),
            "run_id": str(run.id),
            "node_label": node_label,
            "target_id": run.target_id,
        },
    )
    result = ProjectService().create_task(command=command)
    task_id = getattr(result, "task_id", "") or getattr(result, "id", "") or str(result)
    return {"task_id": str(task_id), "title": title, "status": "created"}


def _execute_task(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Create a project task from workflow config.

    Requires ``config.column_id`` (the board column) and ``config.user_id`` (the
    member creating the to-do). Without a column there is nowhere to put the
    task, so the node is an explicit no-op rather than a failure.
    """
    title = config.get("title", f"Workflow task: {node.get('label', 'Untitled')}")
    description = config.get("description", "")
    column_id = config.get("column_id")
    user_id = config.get("user_id") or config.get("assignee_id")
    project_id = config.get("project_id")

    if not column_id or not user_id:
        return {"status": "skipped", "reason": "task node needs column_id and user_id"}

    try:
        return _create_project_task(
            run,
            title=title,
            description=description,
            column_id=column_id,
            user_id=user_id,
            project_id=project_id,
            node_label=node.get("label", ""),
        )
    except Exception as exc:
        logger.exception("workflow_task_node_failed run_id=%s title=%s", run.id, title)
        raise WorkflowActionError(f"task node failed: {exc}") from exc


def _execute_ai(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Trigger an AI agent execution."""
    agent_id = config.get("agent_id")
    prompt = config.get("prompt", "")
    workspace_id = str(run.workflow.workspace_id)

    if not agent_id and not prompt:
        return {"status": "skipped", "reason": "no agent_id or prompt configured"}

    try:
        from components.agents.application.service import AgentService

        result = AgentService().execute_agent(
            agent_id=agent_id,
            workspace_id=workspace_id,
            prompt=prompt or f"Workflow step for target {run.target_id}",
            context={
                "workflow_id": str(run.workflow.id),
                "run_id": str(run.id),
                "target_id": run.target_id,
                "target_type": run.target_type,
                "trigger_type": run.trigger_type,
            },
        )
        return {"status": "executed", "agent_id": agent_id, "result_preview": str(result)[:200]}
    except Exception as exc:
        logger.exception("workflow_ai_node_failed run_id=%s agent_id=%s", run.id, agent_id)
        raise WorkflowActionError(f"ai node failed: {exc}") from exc


def _execute_assign(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Assign follow-up on the contact by creating a real assigned to-do.

    DECISION (Phase 2): there is NO membership-level "assignment" mechanism in
    this codebase — ``MembershipService`` has no assign method, ``role``/
    ``persona`` are RBAC fields that must never be set by an automation, and the
    legacy stub imported a ``membership_service`` symbol that does not exist. So
    rather than leave a fake "assigned" success dict (which would silently do
    nothing), ``assign`` is a thin alias over ``ProjectService().create_task`` —
    it creates a real to-do for the assignee about this contact. This is the
    fallback the task spec calls for and matches how the ``task`` node already
    produces work.

    Config: ``column_id`` (board column the to-do lands in) and ``assignee_id``
    (the member who owns the to-do; must be able to post to that column's team).
    Without ``column_id`` there is nowhere to create the to-do, so the node is an
    explicit no-op rather than a failure.
    """
    assignee_id = config.get("assignee_id") or config.get("user_id")
    column_id = config.get("column_id")
    target_id = run.target_id

    if not assignee_id:
        return {"status": "skipped", "reason": "no assignee_id configured"}
    if not column_id:
        return {"status": "skipped", "reason": "assign node needs column_id for the to-do"}

    title = config.get("title") or f"Follow up with contact {target_id}"
    description = config.get("description", "")

    try:
        result = _create_project_task(
            run,
            title=title,
            description=description,
            column_id=column_id,
            user_id=assignee_id,
            project_id=config.get("project_id"),
            node_label=node.get("label", ""),
        )
    except Exception as exc:
        logger.exception("workflow_assign_node_failed run_id=%s target_id=%s", run.id, target_id)
        raise WorkflowActionError(f"assign node failed: {exc}") from exc

    result["assignee_id"] = str(assignee_id)
    result["target_id"] = target_id
    return result


def _get_or_create_tag(name: str):
    """Get or create a workspaces ``Tag`` by name (the M2M target)."""
    from infrastructure.persistence.workspaces.models import Tag

    tag, _ = Tag.objects.get_or_create(name=name)
    return tag


def _execute_add_tag(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Add a workspace-scoped tag to the workflow's directory contact.

    The contact is the ``WorkspaceMembership`` for ``(workspace, target user)``;
    the tag is added to its ``tags`` M2M. Keela's "Add Tag" action.
    """
    tag_name = (config.get("tag") or config.get("tag_name") or "").strip()
    if not tag_name:
        return {"status": "skipped", "reason": "no tag configured"}

    membership = _resolve_membership(run)
    if membership is None:
        # Genuine no-op: no directory contact to tag (group target, or the
        # member was removed). Not a failure.
        return {"status": "skipped", "reason": "no membership contact for target"}

    try:
        tag = _get_or_create_tag(tag_name)
        membership.tags.add(tag)
    except Exception as exc:
        logger.exception(
            "workflow_add_tag_failed run_id=%s target_id=%s tag=%s",
            run.id,
            run.target_id,
            tag_name,
        )
        raise WorkflowActionError(f"add_tag failed: {exc}") from exc

    return {"status": "tagged", "tag": tag_name, "target_id": run.target_id}


def _execute_remove_tag(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Remove a workspace-scoped tag from the workflow's directory contact."""
    tag_name = (config.get("tag") or config.get("tag_name") or "").strip()
    if not tag_name:
        return {"status": "skipped", "reason": "no tag configured"}

    membership = _resolve_membership(run)
    if membership is None:
        return {"status": "skipped", "reason": "no membership contact for target"}

    try:
        from infrastructure.persistence.workspaces.models import Tag

        # Remove every matching tag row (tag names aren't unique-constrained).
        tags = list(Tag.objects.filter(name=tag_name))
        if tags:
            membership.tags.remove(*tags)
    except Exception as exc:
        logger.exception(
            "workflow_remove_tag_failed run_id=%s target_id=%s tag=%s",
            run.id,
            run.target_id,
            tag_name,
        )
        raise WorkflowActionError(f"remove_tag failed: {exc}") from exc

    return {"status": "untagged", "tag": tag_name, "target_id": run.target_id}


def _execute_update_field(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Update an allow-listed CRM field on the contact's UserProfile.

    Only fields in ``_UPDATE_FIELD_ALLOWLIST`` may be written — a non-allow-listed
    field is a hard failure (fail loudly), NOT a silent skip, so a misconfigured
    automation surfaces instead of silently doing nothing or, worse, attempting
    to write a sensitive field.
    """
    field_name = (config.get("field") or "").strip()
    value = config.get("value", "")

    if not field_name:
        return {"status": "skipped", "reason": "no field configured"}

    if field_name not in _UPDATE_FIELD_ALLOWLIST:
        logger.warning(
            "workflow_update_field_rejected run_id=%s field=%s (not allow-listed)",
            run.id,
            field_name,
        )
        raise WorkflowActionError(f"update_field {field_name!r} is not an updatable field")

    user = _resolve_contact_user(run)
    if user is None:
        return {"status": "skipped", "reason": "target is not a contact user"}

    try:
        from infrastructure.persistence.users.models import UserProfile

        profile, _ = UserProfile.objects.get_or_create(user=user)
        setattr(profile, field_name, value)
        profile.save(update_fields=[field_name])
    except Exception as exc:
        logger.exception(
            "workflow_update_field_failed run_id=%s target_id=%s field=%s",
            run.id,
            run.target_id,
            field_name,
        )
        raise WorkflowActionError(f"update_field failed: {exc}") from exc

    return {"status": "updated", "field": field_name, "target_id": run.target_id}


def _assert_safe_webhook_url(url: str) -> None:
    """SSRF guard: only http(s) to PUBLIC addresses.

    Customers supply this URL, so without a guard a node could reach internal
    services or the cloud metadata endpoint (169.254.169.254). We require an
    http(s) scheme and resolve the host, rejecting any private / loopback /
    link-local / reserved / multicast / unspecified address. Raises
    WorkflowActionError (fail loudly) on violation.

    Note: this is resolve-then-validate; it does not pin the resolved IP for the
    actual request, so it is not hardened against DNS-rebinding. That (pinning
    the validated IP) is a tracked follow-up; this closes the common-case hole.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WorkflowActionError(f"webhook url scheme not allowed: {parsed.scheme or 'none'}")
    host = parsed.hostname
    if not host:
        raise WorkflowActionError("webhook url has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WorkflowActionError(f"webhook host did not resolve: {host}") from exc
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise WorkflowActionError(f"webhook host resolved to an invalid address: {ip_str}") from exc
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise WorkflowActionError(f"webhook url resolves to a non-public address ({ip}) — blocked")


def _execute_webhook(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Call an external webhook URL."""
    url = config.get("url")
    method = config.get("method", "POST").upper()
    headers = config.get("headers") or {}
    timeout = config.get("timeout", 30)

    if not url:
        return {"status": "skipped", "reason": "no webhook URL configured"}

    # Block SSRF (internal hosts / cloud metadata) before making the request.
    _assert_safe_webhook_url(url)

    import requests as http_client

    payload = {
        "workflow_id": str(run.workflow.id),
        "run_id": str(run.id),
        "target_id": run.target_id,
        "target_type": run.target_type,
        "trigger_type": run.trigger_type,
        "trigger_payload": run.trigger_payload or {},
        "node_id": node.get("id"),
        "node_label": node.get("label", ""),
        "timestamp": timezone.now().isoformat(),
    }

    try:
        if method == "GET":
            response = http_client.get(url, headers=headers, params=payload, timeout=timeout)
        else:
            response = http_client.post(url, json=payload, headers=headers, timeout=timeout)

        response.raise_for_status()
        return {
            "status": "delivered",
            "url": url,
            "http_status": response.status_code,
            "response_preview": response.text[:200],
        }
    except Exception as exc:
        logger.exception("workflow_webhook_node_failed run_id=%s", run.id)
        raise WorkflowActionError(f"webhook node failed: {exc}") from exc


def _execute_publish_event(run: Any, node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Publish a shared-kernel domain event via the EventPublisher.

    Phase 4 of the Agents-as-Teammates migration uses this node to
    fan workflow outcomes onto the platform event bus — downstream
    specialist agents subscribe to the resulting domain events and
    take follow-up action (e.g. ``TaskAcceptedFromBoard`` → budget
    specialist queues a review).

    Node ``config`` shape::

        {
            "event_type": "task_accepted_from_board",  # dispatch key
            "filters": {                                 # optional
                "task_source_type_prefix": "ai.",
                "new_column_title": "Accepted"
            }
        }

    Only ``task_accepted_from_board`` is supported in this PR. Adding a
    second event type means adding a new branch here + a new event
    class in the shared kernel — both small, scoped changes.

    The node reads ``run.trigger_payload`` (the original
    ``task_moved_column`` event payload) for the IDs to populate on
    the published event.
    """
    event_type = (config.get("event_type") or "").strip()
    filters = config.get("filters") or {}
    payload = run.trigger_payload or {}

    # Filter: source_type prefix (e.g. "ai." matches only AI tasks).
    prefix = filters.get("task_source_type_prefix") or ""
    if prefix and not (payload.get("task_source_type") or "").startswith(prefix):
        return {"status": "skipped", "reason": "source_type_prefix mismatch"}

    # Filter: destination column title. The trigger emits
    # ``new_column_id``; the engine resolves the title here so the
    # filter is human-readable in the template config.
    required_title = (filters.get("new_column_title") or "").strip()
    if required_title:
        from infrastructure.persistence.project.models import Column

        column_id = payload.get("new_column_id")
        column = Column.objects.filter(id=column_id).only("title").first() if column_id else None
        actual_title = (column.title if column else "") or ""
        if actual_title.lower() != required_title.lower():
            return {
                "status": "skipped",
                "reason": "new_column_title mismatch",
                "actual": actual_title,
            }

    if event_type == "task_accepted_from_board":
        return _publish_task_accepted_from_board(run, payload)

    return {"status": "skipped", "reason": f"unknown event_type {event_type!r}"}


def _publish_task_accepted_from_board(run: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from uuid import UUID

    from components.shared_kernel.domain.events import TaskAcceptedFromBoard
    from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
        CeleryEventPublisher,
    )

    def _to_uuid(value):
        if not value:
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    workspace_id = _to_uuid(payload.get("workspace_id"))
    task_id = _to_uuid(payload.get("task_id"))
    if workspace_id is None or task_id is None:
        raise WorkflowActionError("publish_event trigger payload missing workspace_id or task_id")

    event = TaskAcceptedFromBoard(
        workspace_id=workspace_id,
        task_id=task_id,
        source_type=payload.get("task_source_type") or "",
        accepted_at=timezone.now(),
        user_id=_to_uuid(payload.get("user_id")),
        previous_column_id=_to_uuid(payload.get("previous_column_id")),
        new_column_id=_to_uuid(payload.get("new_column_id")),
    )
    try:
        CeleryEventPublisher().publish(event)
        return {
            "status": "delivered",
            "event_type": "task_accepted_from_board",
            "event_id": str(event.event_id),
        }
    except Exception as exc:
        logger.exception(
            "publish_event_failed event_type=task_accepted_from_board run_id=%s",
            run.id,
        )
        raise WorkflowActionError(f"publish_event failed: {exc}") from exc


_EXECUTORS = {
    "message": _execute_message,
    "task": _execute_task,
    "ai": _execute_ai,
    "assign": _execute_assign,
    "add_tag": _execute_add_tag,
    "remove_tag": _execute_remove_tag,
    "update_field": _execute_update_field,
    "webhook": _execute_webhook,
    "publish_event": _execute_publish_event,
}
