"""Signal bridge — DeepRunLog post_save → publish realtime event.

Every ``DeepRunLog`` insert produces a ``resource.event`` envelope that
the agent-run dashboard + the per-run progress UI consume via
WebSocket. The bridge is best-effort: failures (no Redis, no channel
layer, transient publish error) log and continue — they must never
block the upstream save that just happened.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.1 and the
``RealtimeEventPort`` interface for the envelope shape.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


def _handle_deep_run_log_save(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        deep_run = getattr(instance, "deep_run", None)
        if deep_run is None:
            return
        workspace_id = (
            str(deep_run.workspace_id) if deep_run.workspace_id else ""
        )
        plan_id = deep_run.plan_id or str(deep_run.thread_id or "")
        if not plan_id:
            return

        # Snapshot the values needed by the publisher BEFORE
        # ``on_commit`` fires. The closure runs after the request
        # commits — by then ``instance`` may already be GC'd and we
        # can't rely on lazy attribute access. ``deep_run.status`` in
        # particular changes between log creation and run completion;
        # we want the status that was true *when the event was
        # created*.
        status_at_event = instance.status or deep_run.status or "running"
        agent_type_at_event = instance.agent_type or ""
        tool_name_at_event = instance.tool_name or ""
        event_type = instance.event_type or "log"
        log_id = instance.id
        deep_run_id = deep_run.id
        thread_id = deep_run.thread_id
        payload_dict = dict(instance.payload or {})
        progress_percent = int(payload_dict.get("progress_percent") or 0)

        from django.conf import settings
        from django.db import transaction
        from components.shared_platform.application.providers.realtime_event_provider import (
            get_realtime_event_publisher,
        )

        publisher = get_realtime_event_publisher(
            enabled=getattr(settings, "REALTIME_EVENTS_ENABLED", True)
        )

        def _publish() -> None:
            try:
                publisher.publish(
                    workspace_id=workspace_id,
                    resource_type="agent_run",
                    resource_id=plan_id,
                    event_name=event_type,
                    status=status_at_event,
                    progress_percent=progress_percent,
                    payload={
                        "agent_type": agent_type_at_event,
                        "tool_name": tool_name_at_event,
                        "log_id": log_id,
                        "deep_run_id": deep_run_id,
                        "thread_id": thread_id,
                        **payload_dict,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "deep_run_log_realtime_publish_failed log_id=%s",
                    log_id,
                )

        # The agent-chat endpoint runs under ``ATOMIC_REQUESTS=True``,
        # so when this handler fires post_save, the row hasn't been
        # committed yet. If we publish to Channels immediately the
        # subscriber gets notified before the row is visible to other
        # DB connections (and before the WS event handler can fetch
        # the snapshot). ``transaction.on_commit`` defers the publish
        # to the moment the request actually commits, eliminating the
        # race. If we're not in a transaction, ``on_commit`` calls
        # the function synchronously — same effect, no harm.
        transaction.on_commit(_publish)
    except Exception:  # noqa: BLE001
        logger.exception(
            "deep_run_log_realtime_publish_failed log_id=%s",
            getattr(instance, "id", None),
        )


class DjangoDeepRunRealtimeSignalBridge:
    """Wires the post_save handler. Idempotent — registers with a
    stable ``dispatch_uid`` so re-importing the module doesn't fan out
    duplicate handlers."""

    DISPATCH_UID = "agents:deep_run_log_post_save_realtime"

    @staticmethod
    def register():
        from infrastructure.persistence.ai.agents.models import DeepRunLog

        post_save.connect(
            _handle_deep_run_log_save,
            sender=DeepRunLog,
            dispatch_uid=DjangoDeepRunRealtimeSignalBridge.DISPATCH_UID,
        )
