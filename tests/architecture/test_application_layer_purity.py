"""Unified application-layer purity guardrail.

The application layer (``components/<ctx>/application/``) must be
framework-free and must not import legacy ``apps.*`` modules.  It may
only depend on:

  * Python stdlib
  * Its own bounded context's domain, ports, and other application code
  * ``components.shared_kernel``
  * ``components.<ctx>.infrastructure.*`` **only** from provider files
    (composition roots) that wire adapters to ports

This single test replaces the per-context ``test_<ctx>_application_import_rules``
files by scanning **every** context automatically.  A new context gets the
guardrail for free the moment ``components/<ctx>/application/`` exists.

Banned prefix rationale:

  * ``apps`` — legacy Django app layer; must be behind ports/adapters
  * ``django`` — framework dependency belongs in infrastructure
  * ``rest_framework`` — presentation concern
  * ``celery`` — infrastructure concern
  * ``stripe`` / ``braintree`` — payment provider SDKs
  * ``requests`` — HTTP client, infrastructure
  * ``redis`` — cache/messaging, infrastructure
  * ``elasticsearch`` / ``elasticsearch_dsl`` — search infrastructure
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# ── Canonical banned prefixes ──────────────────────────────────────────
# Every context's application layer is checked against this set.
BANNED_PREFIXES = {
    "apps",
    "django",
    "rest_framework",
    "celery",
    "stripe",
    "braintree",
    "requests",
    "redis",
    "elasticsearch",
    "elasticsearch_dsl",
}

# ── Transitional allowlist ─────────────────────────────────────────────
# (context, file_stem) pairs that are temporarily exempt.
# Each entry MUST have a tracking comment explaining what blocks removal.
_TRANSITIONAL_ALLOWLIST: set[tuple[str, str]] = set()


# ── ORM-purity guard (test_application_layer_is_orm_free) ──────────────
# The application layer must be ORM-free: business logic depends on ports
# (injected repositories), never on Django ORM models directly. Reaching
# for ``infrastructure.persistence.<app>.models`` from a use case / service
# / handler / facade violates architecture-manifesto Rule 2 ("dependencies
# point inward; application depends on domain only") and the architecture
# skill's C2 rule (a context must not WRITE another context's persistence).
# It is invisible to the framework-purity test above (``infrastructure`` is
# not a banned prefix) and to the cross-context boundary test (which only
# flags ``components.<ctx>.infrastructure``, not the shared persistence root).
#
# EXCEPTION — ``application/providers/`` composition roots. Per this file's
# header (and architecture-manifesto Rule 9) providers are the sanctioned
# place where the application layer wires ORM-backed adapters to ports via
# deferred ``from infrastructure.persistence...`` imports. They are exempt
# by construction (see ``_is_provider_composition_root``), NOT allowlisted.
#
# TRANSITIONAL: cross-context/app-layer ORM — see architecture audit 2026-08;
# burn down (task #45 for open_draft_pr). Each entry is a pre-existing
# app-layer ORM importer surfaced by this new guard; keyed by
# (context, posix path relative to the context dir). Extend the allowlist
# ONLY to record an existing offender being tracked for removal — never to
# excuse new application-layer ORM access.
_ORM_FREE_ALLOWLIST: set[tuple[str, str]] = {
    # integrations — the C2 WRITE (worst offender): opens a draft PR then
    # mutates project.models.Task/TaskComment from the integrations context.
    # TRANSITIONAL: cross-context/app-layer ORM — see architecture audit
    # 2026-08; burn down (task #45 for open_draft_pr).
    ("integrations", "application/use_cases/open_draft_pr_use_case.py"),
    # integrations — log ingestion/source/pattern services read their own
    # context's ORM (WorkspaceLogSource / AwsOrganizationConnection / rollups)
    # inline; pending repository/port extraction (LogSource subsystem).
    # TRANSITIONAL: app-layer ORM — see architecture audit 2026-08; burn down.
    ("integrations", "application/log_source_service.py"),
    ("integrations", "application/log_ingest_service.py"),
    ("integrations", "application/log_pattern_analyzer_service.py"),
    # agents — orchestrator/services/handlers read Agent/DeepRun/Task/
    # Workspace/AITeammateProfile ORM inline; pending port extraction.
    # TRANSITIONAL: app-layer ORM — see architecture audit 2026-08; burn down.
    ("agents", "application/facades/ai_teammate_facade.py"),
    # ai_governance_service: the CROSS-context reads (project.Task HITL ledger,
    # integrations.GitHubConnection credential surface, workspaces.Workspace
    # kill-switch toggle) are now routed through ports (PR-6). Only its OWN
    # context's ai.* reads (DeepRun/DeepRunLog/Agent/AITeammateProfile) remain —
    # the type-C same-context burndown tracked under PR-10. Entry kept for those.
    ("agents", "application/services/ai_governance_service.py"),
    ("agents", "application/services/detector_cycle.py"),
    ("agents", "application/services/execution_cost_tracker.py"),
    ("agents", "application/services/posture_dashboard_service.py"),
    ("agents", "application/services/posture_service.py"),
    ("agents", "application/use_cases/agent_chat_use_case.py"),
    ("agents", "application/use_cases/set_workspace_agent_capability_use_case.py"),
    # content — RAG index handlers + newsletter use cases read Newsletter/
    # WritingDraft/Workspace ORM inline; pending port extraction.
    # TRANSITIONAL: app-layer ORM — see architecture audit 2026-08; burn down.
    ("content", "application/handlers/rag_index_newsletter_handler.py"),
    ("content", "application/handlers/rag_index_writing_draft_handler.py"),
    ("content", "application/use_cases/dispatch_due_scheduled_newsletters_use_case.py"),
    ("content", "application/use_cases/generate_newsletter_use_case.py"),
    # membership — permission service reads WorkspaceRole ORM inline; pending
    # port extraction.
    # TRANSITIONAL: app-layer ORM — see architecture audit 2026-08; burn down.
    ("membership", "application/services/membership_permission_service.py"),
    # workflow — findings facade reads workflow ORM inline; pending port
    # extraction.
    # TRANSITIONAL: app-layer ORM — see architecture audit 2026-08; burn down.
    ("workflow", "application/facades/ai_findings_workflow_facade.py"),
}


def _is_orm_model_import(mod: str) -> bool:
    """True if *mod* reaches Django ORM models through the shared persistence
    layer — ``infrastructure.persistence.<app>.models`` (the canonical form)
    or any ``infrastructure.<...>.models`` module."""
    if mod == "infrastructure.persistence" or mod.startswith("infrastructure.persistence."):
        return True
    parts = mod.split(".")
    return len(parts) >= 2 and parts[0] == "infrastructure" and parts[-1] == "models"


def _is_provider_composition_root(rel_parts: tuple[str, ...]) -> bool:
    """True for ``application/providers/**`` files. Providers are the
    sanctioned composition roots that wire ORM-backed adapters to ports
    (architecture-manifesto Rule 9); they may defer-import persistence."""
    return "providers" in rel_parts


def _iter_python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(f for f in path.rglob("*.py") if f.is_file())


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


def test_all_application_layers_are_framework_and_legacy_import_free():
    """Every context's application layer must be free of banned imports.

    Scans ``components/*/application/`` for imports from framework
    packages or legacy ``apps.*`` modules.  Violations indicate that
    business logic depends on infrastructure — extract behind a port.
    """
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name

        app_dir = ctx_dir / "application"
        if not app_dir.exists():
            continue

        for src in _iter_python_files(app_dir):
            if src.name == "__init__.py":
                continue

            if (ctx, src.stem) in _TRANSITIONAL_ALLOWLIST:
                continue

            for mod in _imported_modules(src):
                prefix = mod.split(".", 1)[0]
                if prefix in BANNED_PREFIXES:
                    violations.append(f"{src.relative_to(ROOT)} in '{ctx}' application imports banned module: {mod}")

    assert not violations, (
        "Application layers must not import framework or legacy modules "
        "(extract behind a port/adapter):\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_all_port_layers_are_framework_free():
    """Every context's ports layer must be framework-free.

    Ports define contracts using Python ABCs, Protocols, and dataclasses.
    They must not import Django, DRF, or any infrastructure library.
    """
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name

        ports_dir = ctx_dir / "ports"
        if not ports_dir.exists():
            continue

        for src in _iter_python_files(ports_dir):
            if src.name == "__init__.py":
                continue

            for mod in _imported_modules(src):
                prefix = mod.split(".", 1)[0]
                if prefix in BANNED_PREFIXES:
                    violations.append(f"{src.relative_to(ROOT)} in '{ctx}' ports imports banned module: {mod}")

    assert not violations, "Port layers must not import framework or legacy modules:\n" + "\n".join(
        f"  - {v}" for v in violations
    )


def test_application_layer_is_orm_free():
    """No application-layer code may import Django ORM models directly.

    Business logic in ``components/<ctx>/application/`` must reach persistence
    through ports (injected repositories), never by importing
    ``infrastructure.persistence.<app>.models`` (or any ``infrastructure.*.models``).
    A direct ORM import is an architecture-manifesto Rule 2 violation (dependencies
    point inward) and — when the model belongs to another context — an architecture
    skill C2 violation (a context must not read/WRITE another context's persistence).

    This closes a real blind spot: such imports slip past
    ``test_all_application_layers_are_framework_and_legacy_import_free`` (``infrastructure``
    is not a banned prefix) AND past the cross-context boundary test (which only
    inspects ``components.<ctx>.infrastructure``, not the shared persistence root).
    The canonical offender is ``integrations/.../open_draft_pr_use_case.py``, which
    WRITES ``project.models.Task``/``TaskComment`` from the integrations context.

    ``application/providers/`` composition roots are exempt by construction — they
    are the sanctioned place to wire ORM-backed adapters to ports (Rule 9).
    Pre-existing offenders are recorded in ``_ORM_FREE_ALLOWLIST`` with tracking
    comments and must be burned down; NEW app-layer ORM imports fail hard here.
    """
    violations: list[str] = []

    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir() or not (ctx_dir / "__init__.py").exists():
            continue
        ctx = ctx_dir.name

        app_dir = ctx_dir / "application"
        if not app_dir.exists():
            continue

        for src in _iter_python_files(app_dir):
            if src.name == "__init__.py":
                continue

            rel_parts = src.relative_to(ctx_dir).parts
            if _is_provider_composition_root(rel_parts):
                continue

            rel_key = src.relative_to(ctx_dir).as_posix()
            if (ctx, rel_key) in _ORM_FREE_ALLOWLIST:
                continue

            orm_imports = sorted(m for m in _imported_modules(src) if _is_orm_model_import(m))
            for mod in orm_imports:
                violations.append(
                    f"{src.relative_to(ROOT)} in '{ctx}' application imports ORM models "
                    f"directly: {mod}. The application layer must reach persistence "
                    "through a port (injected repository), not the ORM."
                )

    assert not violations, (
        "Application layers must be ORM-free (depend on ports, not ORM models). "
        "Extract the access behind a repository/port, or — if it is a tracked "
        "pre-existing offender — add it to _ORM_FREE_ALLOWLIST with a tracking "
        "comment:\n" + "\n".join(f"  - {v}" for v in violations)
    )
