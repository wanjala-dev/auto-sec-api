"""Tier 3 #14 — measure index freshness for the SLO.

Pure-application use case. Takes the two latest-* ports + an SLO
threshold, returns a frozen ``FreshnessSample`` describing one
workspace's lag and SLO compliance. The Celery task and the
management command both call this; persistence happens in the
caller so the use case stays framework-free per
``.claude/rules/architecture-manifesto.md``.

The SLO target lives on the sample, not as a use-case attribute,
because operators may run the use case ad-hoc with different
thresholds (e.g. "what if we tightened to 5 minutes?") and we want
each sample row to record the threshold it was scored against.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from components.knowledge.application.ports.workspace_event_latest_port import (
    WorkspaceEventLatestPort,
)
from components.knowledge.application.ports.workspace_index_latest_port import (
    WorkspaceIndexLatestPort,
)


# 95% of active workspaces should be indexed within 10 minutes of
# any reindex-triggering event. The 10-minute headroom covers Celery
# queue latency + the embedding API round-trip + the 60-second
# per-workspace debounce. Tier 3 #14 — see roadmap doc for the
# justification.
DEFAULT_SLA_TARGET_SECONDS = 600


@dataclass(frozen=True)
class FreshnessSample:
    """One workspace's measurement.

    Frozen so the caller can't mutate the sample between computing
    it and persisting it — a common foot-gun in long-running batch
    audits where the same dict reference gets reused.

    ``latest_event_time = None`` means the workspace has no
    reindex-triggering events at all (a freshly-created empty
    workspace). The SLO treats that as fresh — lag = 0 — because
    there's nothing for the index to catch up on.

    ``latest_index_time = None`` AND there are events means the
    workspace has events but has never been indexed; lag is then
    the full distance from now. That row will fail the SLO, which
    is the correct signal — the indexer needs to catch up.
    """

    workspace_id: str
    sample_time: datetime
    latest_event_time: Optional[datetime]
    latest_index_time: Optional[datetime]
    lag_seconds: int
    sla_target_seconds: int
    sla_met: bool

    @property
    def has_events(self) -> bool:
        return self.latest_event_time is not None

    @property
    def has_index(self) -> bool:
        return self.latest_index_time is not None


class MeasureIndexFreshnessUseCase:
    """Compute one ``FreshnessSample`` per call."""

    def __init__(
        self,
        *,
        event_latest_port: WorkspaceEventLatestPort,
        index_latest_port: WorkspaceIndexLatestPort,
    ) -> None:
        self._event_latest = event_latest_port
        self._index_latest = index_latest_port

    def execute(
        self,
        *,
        workspace_id: str,
        sample_time: datetime,
        sla_target_seconds: int = DEFAULT_SLA_TARGET_SECONDS,
    ) -> FreshnessSample:
        event_time = self._event_latest.latest_event_time(
            workspace_id=workspace_id
        )
        index_time = self._index_latest.latest_index_time(
            workspace_id=workspace_id
        )

        lag_seconds = _compute_lag_seconds(
            event_time=event_time,
            index_time=index_time,
            sample_time=sample_time,
        )
        return FreshnessSample(
            workspace_id=workspace_id,
            sample_time=sample_time,
            latest_event_time=event_time,
            latest_index_time=index_time,
            lag_seconds=lag_seconds,
            sla_target_seconds=sla_target_seconds,
            sla_met=lag_seconds <= sla_target_seconds,
        )


def _compute_lag_seconds(
    *,
    event_time: Optional[datetime],
    index_time: Optional[datetime],
    sample_time: datetime,
) -> int:
    """The SLO lag formula.

    Four cases:

    1. No events at all → workspace is fresh. Lag = 0.
    2. Events exist, no index yet → lag = (sample_time - event_time).
       Captures "has data, hasn't caught up yet."
    3. Events + index, index newer than event → workspace is fully
       fresh. Lag = 0 (the index already caught up).
    4. Events + index, event newer than index → lag = the difference,
       in seconds. This is the typical case during a write storm.

    Clamped to 0 at the bottom (sub-second drift) and capped at the
    int range at the top (the field is a PositiveIntegerField; ~136
    years of lag would overflow, which would be a bigger problem
    than the cap).
    """
    if event_time is None:
        return 0
    if index_time is None:
        delta = (sample_time - event_time).total_seconds()
    else:
        delta = (event_time - index_time).total_seconds()
    if delta <= 0:
        return 0
    return int(min(delta, 2_147_483_647))
