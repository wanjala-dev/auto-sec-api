"""Use case: list the authenticated user's own login activity.

Framework-free — delegates to the login-activity read port. The result is
a sliceable sequence the REST adapter paginates; each row carries its
linked session (eager-loaded by the adapter, so serialising the device
summary costs no extra queries).
"""

from __future__ import annotations

from collections.abc import Sequence

from components.identity.application.ports.login_activity_query_port import LoginActivityQueryPort
from components.identity.application.queries.login_activity_query import LoginActivityQuery


class ListLoginActivityUseCase:
    """Self view of the auth audit trail (full detail incl. IP + UA)."""

    def __init__(self, *, activity_port: LoginActivityQueryPort) -> None:
        self._activity = activity_port

    def execute(self, query: LoginActivityQuery) -> Sequence:
        return self._activity.list_for_user(query)
