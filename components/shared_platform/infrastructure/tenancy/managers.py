"""Workspace-scoped manager — the forgotten-filter guard.

The bug this prevents is one line::

    Finding.objects.filter(status="open")        # every customer's findings

Nothing about that reads as wrong. It is only wrong because a `workspace_id=`
is missing, and no reviewer catches that reliably forever.

Attach ``WorkspaceScopedManager`` and the filter stops being something anyone
has to remember. Crossing the boundary is still possible — it just has to be
written down, via ``unscoped`` or :func:`without_workspace_scope`, where a
reader and a diff can both see it.

**Fail-closed, like the router.** With no workspace bound this raises rather
than returning everything. The tempting shape::

    if workspace_id is not None:
        qs = qs.filter(workspace_id=workspace_id)
    return qs                     # ← unbound = unfiltered = every tenant

fails open in exactly the way ADR 0029 D4 forbids: the call site looks scoped,
and reads across all customers.
"""

from __future__ import annotations

from django.db import models

from components.shared_platform.infrastructure.tenancy.workspace_context import (
    UnboundWorkspaceError,
    get_current_workspace,
)


class WorkspaceScopedQuerySet(models.QuerySet):
    """A queryset that knows which workspace it belongs to."""

    def for_workspace(self, workspace_id) -> WorkspaceScopedQuerySet:
        """Scope explicitly, ignoring the ambient binding.

        For code that legitimately handles a workspace other than the bound one
        — an admin tool, a migration backfill — and wants that visible.
        """
        return self.filter(workspace_id=workspace_id)


class WorkspaceScopedManager(models.Manager.from_queryset(WorkspaceScopedQuerySet)):
    """Filters every queryset by the bound workspace, or raises."""

    def get_queryset(self):
        workspace_id = get_current_workspace()
        if workspace_id is None:
            raise UnboundWorkspaceError(
                f"No workspace bound while querying {self.model._meta.label}. "
                "Bind one with workspace_context(...), or state the crossing "
                "explicitly with .unscoped / without_workspace_scope(). "
                "Returning every workspace's rows here would look scoped at the "
                "call site and read across all customers."
            )
        return super().get_queryset().filter(workspace_id=workspace_id)


class WorkspaceScopedModel(models.Model):
    """Abstract base: scoped by default, with a named escape hatch.

    ``objects`` filters; ``unscoped`` does not. The asymmetry is deliberate —
    the safe path is the short one, and the dangerous path has to be typed.
    """

    objects = WorkspaceScopedManager()
    unscoped = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Stamp the workspace from context, never from client input.

        Mass-assignment protection: a request body carrying someone else's
        ``workspace`` must not decide where a row lands. If the field is already
        set (a legitimate cross-workspace write, or a fixture) it is left alone;
        what cannot happen is a row created with no workspace at all.
        """
        if not getattr(self, "workspace_id", None):
            workspace_id = get_current_workspace()
            if workspace_id is None:
                raise UnboundWorkspaceError(
                    f"Cannot save {self._meta.label} without a workspace. Bind one, or set workspace_id explicitly."
                )
            self.workspace_id = workspace_id
        super().save(*args, **kwargs)
