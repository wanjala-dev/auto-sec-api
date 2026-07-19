"""Provider for the realtime event publishing port.

Composition root — picks the right adapter based on the ``enabled``
flag the caller supplies. The flag itself is read from settings at
the call site (signal bridges, Celery tasks, etc.) so the application
layer stays Django-free per the architecture manifesto.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.1.
"""

from __future__ import annotations

from components.shared_platform.application.ports.realtime_event_port import (
    RealtimeEventPort,
)


def get_realtime_event_publisher(*, enabled: bool = True) -> RealtimeEventPort:
    """Return a publisher implementing ``RealtimeEventPort``.

    Pass ``enabled=False`` for one-shot CLI commands or environments
    without Redis — the NoOp adapter swallows every publish silently.
    Defaults to the Channels-backed adapter so the production runtime
    publishes for free.
    """
    if not enabled:
        from components.shared_platform.infrastructure.adapters.channels_realtime_event_adapter import (
            NoOpRealtimeEventAdapter,
        )
        return NoOpRealtimeEventAdapter()
    from components.shared_platform.infrastructure.adapters.channels_realtime_event_adapter import (
        ChannelsRealtimeEventAdapter,
    )
    return ChannelsRealtimeEventAdapter()
