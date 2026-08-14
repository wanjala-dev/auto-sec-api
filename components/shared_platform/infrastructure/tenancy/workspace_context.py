"""The current workspace, for the duration of one request or one task.

Tenancy has two levels in autosec and they are not the same thing:

* the **tenant** (`context.py`) decides which *database* — set from the host;
* the **workspace** (here) decides which *rows* — set from the URL, the task
  arguments, or an explicit binding.

On the pooled tier the workspace is the whole of the isolation, which is why
this exists separately: a dedicated tenant has one database and still has
workspaces inside it.

Same rules as the tenant binding, for the same reasons: a `ContextVar` because
autosec is ASGI, and unbound means *error* rather than *everything*.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import UUID


class UnboundWorkspaceError(RuntimeError):
    """Raised when workspace-scoped rows are queried with no workspace bound.

    The counterpart to ``UnboundTenantError``. A manager that quietly returned
    every row when nothing was bound would be worse than no manager at all —
    it would look scoped at the call site and read across every customer.
    """


_current: ContextVar[str | None] = ContextVar("autosec_current_workspace", default=None)


def get_current_workspace() -> str | None:
    return _current.get()


def bind_workspace(workspace_id: str | UUID) -> Token:
    return _current.set(str(workspace_id))


def reset_workspace(token: Token) -> None:
    _current.reset(token)


@contextmanager
def workspace_context(workspace_id: str | UUID) -> Iterator[str]:
    """Bind a workspace for a block, unbinding it even if the block raises."""
    token = bind_workspace(workspace_id)
    try:
        yield str(workspace_id)
    finally:
        reset_workspace(token)


@contextmanager
def without_workspace_scope() -> Iterator[None]:
    """Explicitly operate across workspaces.

    For the genuinely cross-tenant jobs — the daily feed-refresh fan-out, a
    management command sweeping every workspace. Named so the crossing is
    visible in a diff; that is the entire point of having it rather than
    letting "no binding" mean the same thing.
    """
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)
