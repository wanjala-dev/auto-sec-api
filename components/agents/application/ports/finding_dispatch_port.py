"""Port: start triage work for a finding — the agents context's public interface.

The routing engine (grouping, leases, gates, the deep-run enqueue) is agents
infrastructure. Callers outside this context — today the integrations controller
that hosts the operator's "draft a fix PR" action — reach it HERE, through the
application layer, never by importing the infrastructure service (Rule 3 /
architecture fitness function ``test_non_application_layers_do_not_import_other_
contexts_infrastructure``).

The refusal type lives here too, so a caller can map a reason to an HTTP status
without touching infrastructure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DraftFixRefused(Exception):
    """An on-demand draft-fix request could not be started.

    ``reason`` is a stable machine code (``finding_not_found``, ``not_routable``,
    ``draft_pr_exists``, ``ai_unavailable``) — an operator always gets a reason,
    never a dead click.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class FindingDispatchPort(ABC):
    @abstractmethod
    def request_draft_fix(self, *, workspace_id: str, task_id: str, performed_by: str) -> dict:
        """Start "triage this finding and, if every guardrail passes, open its draft PR".

        Returns immediately — implementations MUST enqueue the work, never run the
        deep pipeline in the caller's request. The returned mapping carries the
        finding's new state (``drafting``) and whether a run was already in flight.

        Raises :class:`DraftFixRefused` when the request cannot start at all.
        """
