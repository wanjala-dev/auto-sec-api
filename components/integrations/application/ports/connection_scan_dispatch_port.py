"""Port: kick the posture scan fan-out for a connection once its writes are durable.

Onboarding needs exactly one capability from the scanning side: "now that this
connection is verified and its account links are written, start scanning". The
transaction mechanics (``transaction.on_commit``) and the cross-context hop into
the cloud-posture dispatch seam live in the adapter; this port keeps the
connection service framework-free, per the layer rules.

Deliberately NOT a second dispatch path: the adapter calls the same
``dispatch_connection_scans`` seam the on-demand endpoint and the beat scheduler
call, so the gate, the cooldown and the global in-flight cap apply identically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ConnectionScanDispatchPort(ABC):
    """Post-commit fan-out of per-account scans for one connection."""

    @abstractmethod
    def dispatch_after_commit(self, *, workspace_id: str, connection_id: str) -> dict:
        """Schedule the fan-out to run once the caller's writes have committed.

        Returns ``{"scannable", "enqueued", "blocked", "deferred", "retry_after",
        "settled"}``.

        ``settled`` is the honesty flag: the counts are final only when it is
        True. On the normal request path there is no open transaction by the
        time this is called, so the callback runs inline and the counts are
        real. Inside a surrounding ``atomic()`` block (a test, a batch job) the
        dispatch is genuinely deferred and the counts are not yet knowable — a
        caller must not present zeros from an unsettled result as "nothing to
        scan".

        MUST NOT raise. A dispatch problem cannot be allowed to turn a
        successful verification into a failed one — the connection is verified
        either way, and the scheduled sweep remains the retry path.
        """
        raise NotImplementedError
