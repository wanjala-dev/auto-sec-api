"""Adapter: fan out a connection's posture scans after the verify commits.

Implements :class:`ConnectionScanDispatchPort`. Two concerns, both of which is
why this is an adapter rather than inline service code:

1. **Ordering.** The verification writes the ``AwsAccountLink`` rows the fan-out
   reads, and the Celery worker reads them back over its OWN connection —
   enqueueing before the commit races its own write and the worker can pick up
   a scan for a connection it cannot see yet. ``transaction.on_commit`` is the
   house primitive for that (see ``_dispatch_draft_pr_after_commit``).
2. **Containment.** A dispatch failure must never fail the verification. The
   connection IS verified; the scan is a convenience the scheduled sweep will
   retry. So this logs loudly and swallows — the one place in this change where
   swallowing is correct, and it is bounded to the enqueue.

It reuses the SAME seam as the "Scan now" endpoint and the beat scheduler
(``cloud_posture``'s application-layer scan provider — an allowed cross-context
hop; its infrastructure is not touched), so the ``feature.cloud_posture``
capability gate, the cooldown, the one-in-flight invariant and the global
concurrency cap all apply unchanged. There is exactly one dispatch path for
CSPM, and this is not a second one.
"""

from __future__ import annotations

import logging

from django.db import transaction

from components.integrations.application.ports.connection_scan_dispatch_port import (
    ConnectionScanDispatchPort,
)

logger = logging.getLogger(__name__)

#: Provenance stamped onto every ``ScanRun`` this path creates. Distinct from
#: "manual" (an operator pressed Scan now) and "schedule" (the beat fan-out) so
#: the run history can answer "did connecting actually start anything?".
TRIGGER = "verify"


class PostCommitScanDispatchAdapter(ConnectionScanDispatchPort):
    def dispatch_after_commit(self, *, workspace_id: str, connection_id: str) -> dict:
        outcome: dict = {
            "scannable": 0,
            "enqueued": 0,
            "blocked": 0,
            "deferred": 0,
            "retry_after": None,
            # Set by the seam when it declined to fan out at all (today: the
            # workspace has CSPM switched off). Present unconditionally so
            # callers can read it without knowing whether the callback ran.
            "skipped_reason": None,
            "settled": False,
        }

        def _dispatch() -> None:
            from components.cloud_posture.application.providers.scan_provider import (
                enqueue_connection_scan,
            )

            try:
                counts = enqueue_connection_scan(
                    workspace_id=str(workspace_id),
                    connection_id=str(connection_id),
                    trigger=TRIGGER,
                )
            except Exception:
                # Never fail the verification over a scan enqueue.
                logger.exception(
                    "aws_verify_autoscan_dispatch_failed workspace_id=%s connection_id=%s",
                    workspace_id,
                    connection_id,
                )
                return
            if counts is None:
                logger.warning(
                    "aws_verify_autoscan_connection_missing workspace_id=%s connection_id=%s",
                    workspace_id,
                    connection_id,
                )
                return

            outcome.update(counts)
            outcome["settled"] = True
            logger.info(
                "aws_verify_autoscan workspace_id=%s connection_id=%s scannable=%s enqueued=%s "
                "deferred=%s blocked=%s skipped_reason=%s",
                workspace_id,
                connection_id,
                counts.get("scannable"),
                counts.get("enqueued"),
                counts.get("deferred"),
                counts.get("blocked"),
                counts.get("skipped_reason"),
            )

        transaction.on_commit(_dispatch)
        return outcome
