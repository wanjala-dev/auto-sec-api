"""ORM adapter for workspace AI configuration + per-workspace usage.

The config side stores its JSON in ``AITeammateProfile.config`` under
the ``ai_config`` key (legacy shape — kept as-is for backward
compat). The usage side reads + writes the precomputed
``WorkspaceAIUsage`` row per the ``/architecture`` skill §6a
aggregation rule: increments are O(1) atomic ``F()`` updates and reads
are a single indexed lookup. Window rollovers are owned by the daily
/ monthly reset Celery beat tasks, NOT the increment path.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from components.agents.application.ports.workspace_ai_config_port import (
    WorkspaceAIConfigPort,
)
from components.agents.domain.value_objects.workspace_ai_config import (
    WorkspaceAIConfig,
)

logger = logging.getLogger(__name__)

_CONFIG_KEY = "ai_config"


def _today_utc():
    return timezone.now().date()


def _first_of_month_utc():
    return _today_utc().replace(day=1)


class OrmWorkspaceAIConfigAdapter(WorkspaceAIConfigPort):
    """Django ORM adapter — config in ``AITeammateProfile``, usage in
    ``WorkspaceAIUsage`` aggregation row."""

    # ── Config ───────────────────────────────────────────────────────

    def load(self, workspace_id: str) -> WorkspaceAIConfig:
        from infrastructure.persistence.ai.models import AITeammateProfile

        profile = AITeammateProfile.objects.filter(workspace_id=workspace_id).first()
        if not profile or not profile.config:
            return WorkspaceAIConfig()
        raw = profile.config.get(_CONFIG_KEY)
        return WorkspaceAIConfig.from_dict(raw)

    def save(
        self,
        workspace_id: str,
        config: WorkspaceAIConfig,
        *,
        changed_by_id: str | None = None,
    ) -> None:
        from infrastructure.persistence.ai.models import AITeammateProfile

        profile = AITeammateProfile.objects.filter(workspace_id=workspace_id).first()
        if not profile:
            logger.warning(
                "No AITeammateProfile for workspace %s — cannot save AI config",
                workspace_id,
            )
            return
        previous = self.load(str(workspace_id))
        profile.config = profile.config or {}
        profile.config[_CONFIG_KEY] = config.to_dict()
        profile.save(update_fields=["config", "updated_at"])
        self._record_model_changes(
            workspace_id=str(workspace_id),
            previous=previous,
            current=config,
            changed_by_id=changed_by_id,
        )

    @staticmethod
    def _record_model_changes(
        *,
        workspace_id: str,
        previous: WorkspaceAIConfig,
        current: WorkspaceAIConfig,
        changed_by_id: str | None,
    ) -> None:
        """Append an ``AIModelChangeEvent`` per model field that actually moved.

        ADR 0032 D7.4. ``AIModelChangeEvent`` was defined, indexed, and READ by
        ``ai_analytics_repository`` — and had no writer anywhere in the repo, so
        the model-change annotation on the quality series was permanently empty.
        The model's own docstring named this adapter as its writer; it simply
        never became one. This is that writer.

        Only real changes are recorded: re-saving the same config must not
        litter the series with markers that would read as switch churn. Writes
        are append-only and never raise — a failed annotation must not roll back
        a config the operator has already been told was saved (the config write
        is the durable fact; the marker is telemetry about it).
        """
        pairs = (
            ("preferred_model", previous.preferred_model, current.preferred_model),
            ("fallback_model", previous.fallback_model, current.fallback_model),
        )
        changed = [(field, old, new) for field, old, new in pairs if (old or "") != (new or "")]
        if not changed:
            return
        try:
            from infrastructure.persistence.ai.aggregations.models import AIModelChangeEvent

            AIModelChangeEvent.objects.bulk_create(
                [
                    AIModelChangeEvent(
                        workspace_id=workspace_id,
                        changed_by_id=changed_by_id or None,
                        field=field,
                        old_value=old or "",
                        new_value=new or "",
                    )
                    for field, old, new in changed
                ]
            )
            for field, old, new in changed:
                logger.info(
                    "ai_model_changed workspace_id=%s field=%s old=%s new=%s changed_by=%s",
                    workspace_id,
                    field,
                    old or "(unset)",
                    new,
                    changed_by_id or "(unattributed)",
                )
        except Exception:
            logger.exception(
                "ai_model_change_event write failed workspace_id=%s fields=%s",
                workspace_id,
                [field for field, _, _ in changed],
            )

    # ── Per-user usage (legacy — drives PersonaAILimits cap) ─────────

    def get_messages_used_today(self, workspace_id: str, user_id: str) -> int:
        # The per-user / per-persona cap is a small-N query (counts
        # this user's messages for today only). For org-wide usage use
        # ``get_workspace_messages_today`` — that one is the precomputed
        # aggregation per §6a.
        from infrastructure.persistence.ai.conversations.models import (
            ConversationMessage,
        )

        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return ConversationMessage.objects.filter(
            conversation__metadata__workspace_id=workspace_id,
            conversation__user_id=user_id,
            role="human",
            created_at__gte=today_start,
        ).count()

    # ── Per-workspace usage (GTM cost gate) ──────────────────────────

    def get_workspace_messages_today(self, workspace_id: str) -> int:
        usage = self._get_usage_row(workspace_id)
        if usage is None:
            return 0
        # If the row's daily window is from a prior day, the counter
        # is stale — treat as 0 until the daily reset task rolls it
        # forward. Avoids double-counting on first message after midnight
        # before the beat task has run.
        if usage.daily_window_start != _today_utc():
            return 0
        return int(usage.daily_messages_sent)

    def get_workspace_tokens_this_month(self, workspace_id: str) -> int:
        usage = self._get_usage_row(workspace_id)
        if usage is None:
            return 0
        if usage.monthly_window_start != _first_of_month_utc():
            return 0
        return int(usage.monthly_tokens_used)

    def get_workspace_runs_this_month(self, workspace_id: str) -> int:
        """Metered-AI runs (execute + deep_run) used this month, 0 if stale."""
        usage = self._get_usage_row(workspace_id)
        if usage is None:
            return 0
        if usage.monthly_runs_window_start != _first_of_month_utc():
            return 0
        return int(usage.monthly_runs_used)

    def record_workspace_run(self, workspace_id: str, *, runs: int = 1) -> None:
        """Atomically tally metered-AI runs for the month (own window).

        Mirrors :meth:`increment_workspace_usage` but for the runs dimension
        only — chat never calls this; the metered execute/deep_run chokepoints
        do. Rolls its own monthly window forward on first contact in a new
        month (covers the gap before the monthly reset task runs).
        """
        from infrastructure.persistence.ai.aggregations.models import (
            WorkspaceAIUsage,
        )

        if runs < 0:
            raise ValueError("run counter must be non-negative")

        month_start = _first_of_month_utc()
        with transaction.atomic():
            usage, created = WorkspaceAIUsage.objects.get_or_create(
                workspace_id=workspace_id,
                defaults={
                    "monthly_runs_used": runs,
                    "monthly_runs_window_start": month_start,
                },
            )
            if created:
                return
            if usage.monthly_runs_window_start == month_start:
                updates = {"monthly_runs_used": F("monthly_runs_used") + runs}
            else:
                updates = {
                    "monthly_runs_used": runs,
                    "monthly_runs_window_start": month_start,
                }
            WorkspaceAIUsage.objects.filter(pk=usage.pk).update(**updates)

    def increment_workspace_usage(
        self,
        workspace_id: str,
        *,
        messages: int = 1,
        tokens: int = 0,
    ) -> None:
        from infrastructure.persistence.ai.aggregations.models import (
            WorkspaceAIUsage,
        )

        if messages < 0 or tokens < 0:
            raise ValueError("increment counters must be non-negative")

        today = _today_utc()
        month_start = _first_of_month_utc()
        now = timezone.now()

        # ``select_for_update`` would serialise concurrent chat calls;
        # ``F()`` lets the DB do an atomic in-place increment without
        # blocking. Combined with ``update_or_create`` to ensure the row
        # exists on first contact for a fresh workspace.
        with transaction.atomic():
            usage, created = WorkspaceAIUsage.objects.get_or_create(
                workspace_id=workspace_id,
                defaults={
                    "daily_messages_sent": messages,
                    "daily_window_start": today,
                    "monthly_tokens_used": tokens,
                    "monthly_window_start": month_start,
                    "last_message_at": now,
                },
            )
            if created:
                # Row just inserted with the right values — nothing else
                # to do.
                return

            # Determine which counters to bump-vs-reset based on the
            # window the row currently sits in. Doing it here covers the
            # edge case where a message arrives after midnight before
            # the daily-reset task has run.
            updates: dict = {"last_message_at": now}
            if usage.daily_window_start == today:
                updates["daily_messages_sent"] = F("daily_messages_sent") + messages
            else:
                updates["daily_messages_sent"] = messages
                updates["daily_window_start"] = today

            if usage.monthly_window_start == month_start:
                updates["monthly_tokens_used"] = F("monthly_tokens_used") + tokens
            else:
                updates["monthly_tokens_used"] = tokens
                updates["monthly_window_start"] = month_start

            WorkspaceAIUsage.objects.filter(pk=usage.pk).update(**updates)

    # ── Internal ─────────────────────────────────────────────────────

    def _get_usage_row(self, workspace_id: str):
        from infrastructure.persistence.ai.aggregations.models import (
            WorkspaceAIUsage,
        )

        return WorkspaceAIUsage.objects.filter(workspace_id=workspace_id).first()
