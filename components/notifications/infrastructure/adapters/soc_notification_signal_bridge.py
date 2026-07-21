"""SOC event → notification signal bridge.

Wires the notification dispatcher funnel to the SOC events an operator
cares about, WITHOUT the emitting contexts having to know about
notifications:

* **AI finding filed** — any ``project.Task`` created with an ``ai.*``
  ``source_type`` (detector findings, posture-report cards, sign-off
  escalations — everything ``persist_finding_as_task`` writes) notifies
  the workspace owner. ``ai.sign_off_pending`` cards get needs-human
  wording; everything else gets "filed a new finding" wording.
* **AI kill switch flipped** — ``Workspace.ai_teammate_enabled`` saved
  with ``update_fields=["ai_teammate_enabled"]`` (exactly how
  ``SetAiKillSwitchUseCase`` persists the flip) notifies the workspace
  owner that AI has been stopped / re-enabled.

Both handlers enqueue ``notifications.dispatch_notification_async`` after
commit — the funnel then applies preference gating, deep-link resolution,
the realtime WS envelope, and the web-push / email delivery ledger.

Signal-bridge pattern (explicit ``post_save.connect`` from an app
``ready()``, never ``@receiver``) per ``.claude/rules/persistence-and-orm.md``.
Handlers are loss-tolerant: a notification enqueue failure is logged and
never breaks the save that triggered it.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.db.transaction import on_commit

logger = logging.getLogger(__name__)

# Provenance label the sign-off materializer stamps on needs-human cards
# (components/sign_off/application/services/materialize_signoff_tasks.py).
_SIGN_OFF_SOURCE_TYPE = "ai.sign_off_pending"


def _dispatch(**kwargs) -> None:
    from components.notifications.workers.tasks import dispatch_notification_async

    on_commit(lambda: dispatch_notification_async.apply_async(kwargs=kwargs))


def _handle_finding_task_created(sender, instance, created, **kwargs):
    """New AI finding card on the board → notify the workspace owner."""
    if not created:
        return
    source_type = getattr(instance, "source_type", "") or ""
    if not source_type.startswith("ai."):
        return
    try:
        workspace = instance.workspace
        owner_id = getattr(workspace, "workspace_owner_id", None)
        if owner_id is None:
            return

        title = (instance.title or "").strip() or "an untitled finding"
        if source_type == _SIGN_OFF_SOURCE_TYPE:
            verb = f"escalated for your sign-off: {title}"
            kind = "soc.sign_off_pending"
        else:
            verb = f"filed a new finding: {title}"
            kind = "soc.finding_filed"

        _dispatch(
            recipient_id=str(owner_id),
            actor_id=str(instance.created_by_id),
            verb=verb,
            notification_type="ai_event",
            workspace_id=str(instance.workspace_id),
            target_ref=["project", "task", str(instance.pk)],
            allow_self_notify=True,
            metadata={
                "kind": kind,
                "task_id": str(instance.pk),
                "source_type": source_type,
            },
        )
    except Exception:
        logger.exception(
            "soc_finding_notification_enqueue_failed task_id=%s workspace_id=%s",
            getattr(instance, "pk", None),
            getattr(instance, "workspace_id", None),
        )


def _handle_kill_switch_flipped(sender, instance, created, update_fields=None, **kwargs):
    """``ai_teammate_enabled`` flip → notify the workspace owner."""
    if created:
        return
    if not update_fields or "ai_teammate_enabled" not in set(update_fields):
        return
    try:
        owner_id = getattr(instance, "workspace_owner_id", None)
        if owner_id is None:
            return

        enabled = bool(instance.ai_teammate_enabled)
        verb = (
            "re-enabled the AI teammate (kill switch lifted)"
            if enabled
            else "stopped the AI teammate (kill switch tripped)"
        )
        _dispatch(
            recipient_id=str(owner_id),
            actor_id=str(owner_id),
            verb=verb,
            notification_type="system",
            workspace_id=str(instance.pk),
            allow_self_notify=True,
            metadata={"kind": "soc.ai_kill_switch", "enabled": enabled},
        )
    except Exception:
        logger.exception(
            "soc_kill_switch_notification_enqueue_failed workspace_id=%s",
            getattr(instance, "pk", None),
        )


class SocNotificationSignalBridge:
    """Explicit signal registration, called from the notifications app ``ready()``."""

    @staticmethod
    def register() -> None:
        from django.apps import apps

        post_save.connect(
            _handle_finding_task_created,
            sender=apps.get_model("project", "Task"),
            dispatch_uid="notifications:soc_finding_task_post_save",
        )
        post_save.connect(
            _handle_kill_switch_flipped,
            sender=apps.get_model("workspaces", "Workspace"),
            dispatch_uid="notifications:soc_kill_switch_post_save",
        )
