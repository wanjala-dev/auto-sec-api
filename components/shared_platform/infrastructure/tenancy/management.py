"""Tenant binding for management commands.

A command has no host and no URL either, so it hits the same gap as a Celery
task — with one difference that matters: there are 99 of them and editing 99
files is how you get 97 done.

So the binding happens at the single entry point every command goes through,
``manage.py``, rather than in a base class each command must remember to
inherit. One place, no per-command discipline, and future commands are covered
the day they are written.

**What gets bound, and what deliberately does not.**

* The **tenant** is bound to POOLED. A command legitimately operates on the
  shared database — migrations, seeds, backfills, the demo bootstrap — so
  refusing to route at all would break every one of them.
* The **workspace** is left UNBOUND. Most commands are cross-workspace by
  nature, and a workspace-scoped queryset inside one should be a deliberate
  act: either ``--workspace`` plus :func:`workspace_context`, or an explicit
  ``without_workspace_scope()`` / ``.unscoped``. Leaving it unbound means the
  scoped manager raises and the author has to say which they meant.

That asymmetry is the whole design: the database is safe to reach, the rows are
not, and the difference has to be written down.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from components.shared_platform.infrastructure.tenancy.context import pooled_context


def run_management_command(argv: Sequence[str] | None = None) -> None:
    """``execute_from_command_line`` with the pooled tenant bound.

    Called from ``manage.py``. Kept here rather than inline so the reasoning
    above lives next to the tenancy code it belongs to, and so tests can drive
    it directly.
    """
    from django.core.management import execute_from_command_line

    with pooled_context():
        execute_from_command_line(list(argv if argv is not None else sys.argv))
