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

--------------------------------------------------------------------------------

**Reaching a tenant that is NOT the pool — ``--tenant`` / ``--all-tenants``.**

Pooled is the right DEFAULT and stays the default: with no flag, every command
behaves exactly as it always has. But for months it was also the only option,
and that made a dedicated tenant's database unreachable by *every* management
command — no backfill, no seed, no data fix, ever, for the customers who pay
for their own database.

That is not theoretical. On 2026-08-19 ``reindex_workspaces --all --sync
--force`` took the pooled database to 0 NULL embeddings of 88 while
``tenant_faura`` (4 of 4 NULL) and ``tenant_wanjala`` (6 of 6 NULL) were
untouched — the command never saw those databases, and reported success.
Their RAG search silently returned zero hits. The workaround in the field was
per-command: ``provision_tenant`` opens its own ``tenant_context`` in its
handler. Solving it once, generically, is what this module now does::

    python manage.py reindex_workspaces --all --sync --tenant faura
    python manage.py reindex_workspaces --all --sync --all-tenants

Both flags are consumed HERE and stripped from ``argv`` before Django parses
it, so no command has to declare them and none can collide with them (verified:
no command in the tree defines ``--tenant`` or ``--all-tenants``).

Three properties this had to have, because getting any of them wrong is worse
than not having the flag at all:

1. **Fail closed, loudly.** An unknown, deactivated, or mis-provisioned tenant
   exits non-zero with a message and NEVER runs the command. A silent fall back
   to pooled would be a cross-tenant write — the worst failure available here,
   and precisely the shape ADR 0029 D4 forbids in the router.
2. **No state leaks between tenants.** Each scope is fully bound and fully
   unbound around its own run, via the same :class:`TenantScope.bind` the beat
   fan-out uses. ``--all-tenants`` enumerates through :func:`sweep_scopes`, so
   an operator command and a scheduled sweep can never disagree about which
   tenants exist.
3. **``--tenant`` on a POOLED tenant scopes the rows too.** On the shared
   database the workspace is the entire isolation, so binding only "pooled"
   would leave ``--tenant senso`` touching every customer in the pool while
   reading, at the call site, as though it were scoped. A pooled tenant whose
   registry row pins no workspace is therefore refused rather than silently
   widened — run without ``--tenant`` if the whole pool is what you meant.
   A DEDICATED tenant binds no workspace: there the database is the isolation
   and the run covers the whole tenant, which is what a backfill needs.

``provision_tenant`` deliberately does NOT converge onto this mechanism. It
cannot: it is what creates the registry row, and ``--tenant`` resolves through
that row. Its in-handler binding is the bootstrap case, not a duplicate.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from components.shared_platform.infrastructure.tenancy.context import pooled_context
from components.shared_platform.infrastructure.tenancy.sweep import (
    POOLED_ALIAS,
    TenantScope,
    sweep_scopes,
)

#: Global flags this entry point owns. Reserved names: a command that declares
#: either of these would shadow them, so don't.
TENANT_FLAG = "--tenant"
ALL_TENANTS_FLAG = "--all-tenants"


class TenantSelectionError(Exception):
    """The operator asked for a tenant we will not run against.

    Deliberately fatal rather than degrading: every alternative to stopping
    here — pooled, "the first match", "skip it" — writes one customer's data
    somewhere it does not belong.
    """


@dataclass(frozen=True)
class TenantSelection:
    """What the operator asked for on the command line."""

    subdomain: str | None = None
    all_tenants: bool = False


# ── argv ────────────────────────────────────────────────────────────────────


def extract_tenant_selection(argv: Sequence[str]) -> tuple[list[str], TenantSelection | None]:
    """Split the tenant flags out of *argv*.

    Returns the argv Django should parse (flags removed) and the selection, or
    ``None`` when no flag was given — the untouched, pooled, status-quo path.
    Pure argv handling: no Django, no database, no settings, so it is safe to
    run before ``django.setup()`` and cheap to test.
    """
    remaining: list[str] = []
    subdomain: str | None = None
    all_tenants = False

    items = list(argv)
    index = 0
    while index < len(items):
        token = items[index]

        if token == ALL_TENANTS_FLAG:
            all_tenants = True
            index += 1
            continue

        if token == TENANT_FLAG or token.startswith(f"{TENANT_FLAG}="):
            if subdomain is not None:
                raise TenantSelectionError(f"{TENANT_FLAG} was given more than once — name exactly one tenant.")
            if token.startswith(f"{TENANT_FLAG}="):
                value = token.split("=", 1)[1]
                index += 1
            else:
                value = items[index + 1] if index + 1 < len(items) else ""
                index += 2
            if not value.strip() or value.startswith("-"):
                raise TenantSelectionError(
                    f"{TENANT_FLAG} needs a tenant subdomain, e.g. {TENANT_FLAG} faura. "
                    "Refusing to guess which customer you meant."
                )
            subdomain = value.strip().lower()
            continue

        remaining.append(token)
        index += 1

    if all_tenants and subdomain is not None:
        raise TenantSelectionError(
            f"{TENANT_FLAG} and {ALL_TENANTS_FLAG} are mutually exclusive — one tenant, or every tenant, not both."
        )
    if not all_tenants and subdomain is None:
        return remaining, None
    return remaining, TenantSelection(subdomain=subdomain, all_tenants=all_tenants)


# ── registry ────────────────────────────────────────────────────────────────


def scope_for_subdomain(subdomain: str) -> TenantScope:
    """The scope for ONE registered tenant, or raise.

    Every failure path here raises. There is no branch that returns the pooled
    scope for an input we could not resolve, because "I could not find the
    tenant you named, so I used the shared database" is how a data fix lands in
    the wrong customer's rows while the log line reads ``completed``.
    """
    from django.conf import settings

    from components.shared_platform.infrastructure.tenancy.context import KIND_DEDICATED
    from infrastructure.persistence.tenancy.models import Tenant

    wanted = subdomain.strip().lower()
    row = Tenant.objects.filter(subdomain=wanted).first()
    if row is None:
        known = ", ".join(Tenant.objects.filter(is_active=True).values_list("subdomain", flat=True)) or "(none)"
        raise TenantSelectionError(
            f"no tenant is registered with subdomain {wanted!r}. Active tenants: {known}. "
            "Not running: resolving an unknown tenant to the pooled database would write "
            "into the wrong customer's data."
        )
    if not row.is_active:
        raise TenantSelectionError(
            f"tenant {wanted!r} is deactivated. Its front door 404s, and background work must not "
            "keep operating on it either. Reactivate the registry row first if this is intended."
        )

    if row.isolation_mode == KIND_DEDICATED:
        if row.db_alias not in settings.DATABASES:
            raise TenantSelectionError(
                f"tenant {wanted!r} is dedicated but its connection alias {row.db_alias!r} is not in "
                "settings.DATABASES — the registry row landed before the deploy config did. Add it to "
                "TENANT_DATABASE_URLS and restart the deployments, then re-run. (Not falling back to "
                "the pooled database: that is a different customer's data.)"
            )
        return TenantScope(label=row.subdomain, db_alias=row.db_alias)

    # Pooled: the database is shared, so the WORKSPACE is the isolation.
    if row.workspace_id is None:
        raise TenantSelectionError(
            f"tenant {wanted!r} is pooled and its registry row pins no workspace, so there is nothing to "
            "scope this run to — on the shared database every pooled customer's rows sit side by side. "
            "Run without --tenant if you meant the whole pool, or pin workspace_id on the registry row."
        )
    return TenantScope(label=row.subdomain, db_alias=POOLED_ALIAS, workspace_id=str(row.workspace_id))


def scopes_for_selection(selection: TenantSelection) -> list[TenantScope]:
    """Every scope the run must visit, in order.

    ``--all-tenants`` means every DATABASE: the pool once (cross-workspace, as
    a pool-wide backfill needs) then each dedicated tenant. It reuses the beat
    fan-out's enumeration rather than growing a second list of tenants.
    """
    if selection.all_tenants:
        return sweep_scopes()
    assert selection.subdomain is not None  # guaranteed by extract_tenant_selection
    return [scope_for_subdomain(selection.subdomain)]


# ── entry point ─────────────────────────────────────────────────────────────


def run_management_command(argv: Sequence[str] | None = None) -> None:
    """``execute_from_command_line``, tenant-bound.

    Called from ``manage.py``. Kept here rather than inline so the reasoning
    above lives next to the tenancy code it belongs to, and so tests can drive
    it directly.
    """
    from django.core.management import execute_from_command_line

    items = list(argv if argv is not None else sys.argv)
    try:
        items, selection = extract_tenant_selection(items)
    except TenantSelectionError as exc:
        _die(exc)

    if selection is None:
        # The default, and the overwhelming majority of runs: unchanged.
        with pooled_context():
            execute_from_command_line(items)
        return

    # A tenant flag was given, so the registry has to be read — which is a
    # query, which needs the app registry. `execute_from_command_line` would
    # call this itself; calling it early is idempotent.
    import django

    django.setup()

    try:
        scopes = scopes_for_selection(selection)
    except TenantSelectionError as exc:
        _die(exc)

    for scope in scopes:
        # stderr, so stdout stays whatever the command wrote. Without this an
        # --all-tenants run is N blocks of output with no way to tell which
        # customer each belongs to.
        sys.stderr.write(f"[tenant] {scope.label} → {scope.db_alias}{_workspace_note(scope)}\n")
        sys.stderr.flush()
        with scope.bind():
            execute_from_command_line(items)

    sys.stderr.write(f"[tenant] done — {len(scopes)} scope(s): {', '.join(s.label for s in scopes)}\n")


def _workspace_note(scope: TenantScope) -> str:
    return f" (workspace {scope.workspace_id})" if scope.workspace_id else ""


def _die(exc: TenantSelectionError) -> NoReturn:
    """Exit the way Django exits on a ``CommandError`` — message, no traceback."""
    sys.stderr.write(f"CommandError: {exc}\n")
    sys.exit(1)
