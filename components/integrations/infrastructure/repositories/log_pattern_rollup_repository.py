"""Repository for the temporal log-pattern rollups.

The single ORM slot for ``LogPatternRollup`` — the persistent per-(connection,
signature) memory that lets the optimization analyzer reason about logs *over
time* (a pattern is surfaced only when high-frequency AND sustained across runs).
The analyzer stays framework-free and folds each window's counts in through here
(architecture rule: ORM lives in infrastructure repositories, not the application
layer). The counter arithmetic is a write concern and lives here; the *decision*
of which patterns clear their threshold stays in the deterministic analyzer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from infrastructure.persistence.integrations.models import LogPatternRollup


class LogPatternRollupRepository:
    """ORM access for the temporal log-pattern rollups, per connection."""

    def get_or_create(
        self,
        *,
        connection,
        signature: str,
        workspace_id,
        service: str,
        kind: str,
        sample_message: str,
    ) -> LogPatternRollup:
        rollup, _created = LogPatternRollup.objects.get_or_create(
            connection=connection,
            signature=signature,
            defaults={
                "workspace_id": workspace_id,
                "service": service,
                "kind": kind,
                "sample_message": sample_message,
            },
        )
        return rollup

    def record_window(
        self,
        rollup: LogPatternRollup,
        *,
        window_count: int,
        kind: str,
        service: str,
        sample_message: str,
        flagged: bool,
    ) -> LogPatternRollup:
        """Fold one aggregation window into the rollup and persist it.

        ``flagged`` stamps ``last_flagged_at`` when the caller (the analyzer) has
        decided this window's pattern clears its threshold AND is sustained —
        throttling re-flagging so a persistently noisy task doesn't file a card
        every run."""
        rollup.total_count += window_count
        rollup.last_window_count = window_count
        rollup.peak_window_count = max(rollup.peak_window_count, window_count)
        rollup.runs_observed += 1
        rollup.kind = kind
        rollup.service = service
        if not rollup.sample_message:
            rollup.sample_message = sample_message
        if flagged:
            rollup.last_flagged_at = datetime.now(UTC)
        rollup.save()
        return rollup
