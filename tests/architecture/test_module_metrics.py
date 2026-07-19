"""Architecture metrics report.

Generates a snapshot of codebase health indicators that track progress
across the refactor.  Each metric is expressed as a test so the report
runs with the same harness as the other architecture guardrails.

Metrics captured:

  * Largest files by line count (controllers, models, views)
  * Cross-context import density per component
  * Controller ORM allowlist size (transitional entries remaining)
  * Controller line-count distribution
  * Provider SDK touchpoints (stripe, braintree, requests)
  * Signal handler count
  * Application-layer file count per context (migration depth)
  * Management commands with business orchestration
  * Model methods with notification/async side effects
"""

import ast
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"
APPS_DIR = ROOT / "infrastructure" / "persistence"


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text().splitlines())
    except Exception:
        return 0


def _iter_python_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(f for f in path.rglob("*.py") if f.is_file())


def _imported_modules(source_file: Path) -> set[str]:
    try:
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
    except SyntaxError:
        return set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    return imported


# ── Metric: Largest controller files ──────────────────────────────────


def test_report_largest_controllers():
    """Report the 15 largest controller files by line count."""
    controllers = []
    for ctx_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not ctx_dir.is_dir():
            continue
        api_dir = ctx_dir / "api"
        for src in _iter_python_files(api_dir):
            if src.name == "__init__.py":
                continue
            lc = _line_count(src)
            controllers.append((lc, str(src.relative_to(ROOT))))

    controllers.sort(reverse=True)
    top = controllers[:15]

    report = ["Largest controllers by line count:"]
    for lc, path in top:
        report.append(f"  {lc:>5} lines  {path}")

    total_lines = sum(lc for lc, _ in controllers)
    over_200 = sum(1 for lc, _ in controllers if lc > 200)
    over_500 = sum(1 for lc, _ in controllers if lc > 500)
    report.append(f"\n  Total controller files: {len(controllers)}")
    report.append(f"  Total controller lines: {total_lines}")
    report.append(f"  Controllers > 200 lines: {over_200}")
    report.append(f"  Controllers > 500 lines: {over_500}")

    # This is a metrics report, not a pass/fail test.
    # Print the report and always pass.
    print("\n".join(report))


# ── Metric: Cross-context import density ──────────────────────────────


def test_report_cross_context_imports():
    """Report cross-context import counts per component."""
    contexts = sorted(
        d.name for d in COMPONENTS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )

    report = ["Cross-context imports per component:"]
    total_cross = 0

    for ctx in contexts:
        ctx_dir = COMPONENTS_DIR / ctx
        cross_imports = 0
        for src in _iter_python_files(ctx_dir):
            for mod in _imported_modules(src):
                if not mod.startswith("components."):
                    continue
                parts = mod.split(".")
                if len(parts) >= 2:
                    imported_ctx = parts[1]
                    if imported_ctx != ctx and imported_ctx != "shared_kernel":
                        cross_imports += 1

        if cross_imports > 0:
            report.append(f"  {ctx:<20} {cross_imports:>4} cross-context imports")
            total_cross += cross_imports

    report.append(f"\n  Total cross-context imports: {total_cross}")
    print("\n".join(report))


# ── Metric: Controller ORM allowlist size ─────────────────────────────


def test_report_controller_orm_allowlist_size():
    """Report the number of transitional ORM allowlist entries."""
    allowlist_file = ROOT / "tests" / "architecture" / "test_controller_orm_import_rules.py"
    if not allowlist_file.exists():
        print("Controller ORM allowlist file not found.")
        return

    tree = ast.parse(allowlist_file.read_text())
    # Count tuple entries in the set literal
    content = allowlist_file.read_text()
    # Each allowlist entry is a (ctx, module) tuple on its own line(s)
    count = content.count('("')
    print(f"Controller ORM transitional allowlist: ~{count} entries remaining")


# ── Metric: Application-layer depth per context ──────────────────────


def test_report_application_layer_depth():
    """Report application-layer file count per context (migration depth)."""
    contexts = sorted(
        d.name for d in COMPONENTS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )

    report = ["Application-layer file count per context:"]
    total_files = 0

    for ctx in contexts:
        app_dir = COMPONENTS_DIR / ctx / "application"
        files = [f for f in _iter_python_files(app_dir) if f.name != "__init__.py"]
        if files:
            report.append(f"  {ctx:<20} {len(files):>3} application files")
            total_files += len(files)

    report.append(f"\n  Total application-layer files: {total_files}")
    print("\n".join(report))


# ── Metric: Port count per context ───────────────────────────────────


def test_report_port_count():
    """Report port file count per context."""
    contexts = sorted(
        d.name for d in COMPONENTS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )

    report = ["Port count per context:"]
    total_ports = 0

    for ctx in contexts:
        ports_dir = COMPONENTS_DIR / ctx / "ports"
        files = [f for f in _iter_python_files(ports_dir) if f.name != "__init__.py"]
        if files:
            report.append(f"  {ctx:<20} {len(files):>3} ports")
            total_ports += len(files)

    report.append(f"\n  Total ports: {total_ports}")
    print("\n".join(report))


# ── Metric: Infrastructure adapter count ─────────────────────────────


def test_report_infrastructure_depth():
    """Report infrastructure file count per context."""
    contexts = sorted(
        d.name for d in COMPONENTS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
    )

    report = ["Infrastructure files per context:"]
    total = 0

    for ctx in contexts:
        infra_dir = COMPONENTS_DIR / ctx / "infrastructure"
        files = [f for f in _iter_python_files(infra_dir) if f.name != "__init__.py"]
        if files:
            report.append(f"  {ctx:<20} {len(files):>3} infrastructure files")
            total += len(files)

    report.append(f"\n  Total infrastructure files: {total}")
    print("\n".join(report))


# ── Metric: Provider SDK touchpoints ─────────────────────────────────


def test_report_provider_sdk_touchpoints():
    """Report files that import provider SDKs (stripe, braintree, requests)."""
    sdk_prefixes = {"stripe", "braintree", "paypal"}
    touchpoints = []

    for src in _iter_python_files(ROOT):
        if "/.git/" in str(src) or "/__pycache__/" in str(src):
            continue
        if "/tests/" in str(src) or "/examples/" in str(src):
            continue
        for mod in _imported_modules(src):
            prefix = mod.split(".", 1)[0]
            if prefix in sdk_prefixes:
                touchpoints.append((str(src.relative_to(ROOT)), mod))
                break  # one per file

    report = [f"Provider SDK touchpoints: {len(touchpoints)} files"]
    for path, mod in sorted(touchpoints)[:20]:
        report.append(f"  {path}")

    print("\n".join(report))


# ── Metric: Signal handler count ─────────────────────────────────────


def test_report_signal_handlers():
    """Report Django signal handler registrations."""
    signal_patterns = {"receiver", "post_save", "pre_save", "post_delete", "pre_delete", "m2m_changed"}
    handler_files = []

    for src in _iter_python_files(APPS_DIR):
        if "/__pycache__/" in str(src):
            continue
        try:
            content = src.read_text()
        except Exception:
            continue
        if "@receiver" in content or "connect(" in content:
            # Count @receiver decorators
            count = content.count("@receiver")
            if count > 0:
                handler_files.append((count, str(src.relative_to(ROOT))))

    handler_files.sort(reverse=True)
    total_handlers = sum(c for c, _ in handler_files)

    report = [f"Signal handlers: {total_handlers} @receiver decorators in {len(handler_files)} files"]
    for count, path in handler_files[:15]:
        report.append(f"  {count:>3} handlers  {path}")

    print("\n".join(report))


# ── Metric: Management commands with business orchestration ──────────


def test_report_management_commands():
    """Report management commands and their migration status.

    Classifies each management command by:
    - whether it imports from ``components.*`` (migrated/partially migrated)
    - whether it uses Django ORM directly (``apps.*.models``)
    - whether it calls external services (stripe, braintree, requests, celery)
    """
    cmd_dirs = list(ROOT.rglob("management/commands"))
    commands: list[tuple[str, int, bool, bool, bool]] = []  # (path, lines, migrated, orm, external)
    external_prefixes = {"stripe", "braintree", "paypal", "requests", "celery"}

    for cmd_dir in cmd_dirs:
        for src in _iter_python_files(cmd_dir):
            if src.name == "__init__.py":
                continue
            lc = _line_count(src)
            mods = _imported_modules(src)
            has_components = any(m.startswith("components.") for m in mods)
            has_orm = any(
                m.startswith("infrastructure.persistence.") and ".models" in m
                for m in mods
            )
            has_external = any(
                m.split(".", 1)[0] in external_prefixes
                for m in mods
            )
            commands.append((str(src.relative_to(ROOT)), lc, has_components, has_orm, has_external))

    commands.sort(key=lambda x: x[1], reverse=True)

    migrated = sum(1 for _, _, m, _, _ in commands if m)
    with_orm = sum(1 for _, _, _, o, _ in commands if o)
    with_external = sum(1 for _, _, _, _, e in commands if e)

    report = [f"Management commands: {len(commands)} total"]
    report.append(f"  Migrated (uses components.*): {migrated}")
    report.append(f"  Direct ORM (apps.*.models):   {with_orm}")
    report.append(f"  External services:             {with_external}")
    report.append(f"\n  Largest management commands:")
    for path, lc, m, o, e in commands[:10]:
        flags = []
        if m:
            flags.append("migrated")
        if o:
            flags.append("orm")
        if e:
            flags.append("external")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        report.append(f"    {lc:>4} lines  {path}{flag_str}")

    print("\n".join(report))


# ── Metric: Model methods with notification/async side effects ───────


def test_report_model_side_effects():
    """Report Django model files that contain notification or async side effects.

    Looks for patterns in model files that suggest business orchestration
    leaking into the ORM layer: sending emails/notifications, dispatching
    Celery tasks, or calling external services from model methods.
    """
    side_effect_patterns = [
        "send_mail",
        "send_email",
        ".delay(",
        ".apply_async(",
        "notify",
        "dispatch",
        "celery",
        "requests.post",
        "requests.get",
    ]

    flagged: list[tuple[str, int, list[str]]] = []

    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        for models_file in app_dir.rglob("models.py"):
            if "/__pycache__/" in str(models_file):
                continue
            try:
                content = models_file.read_text()
            except Exception:
                continue
            found = []
            for pattern in side_effect_patterns:
                if pattern in content:
                    found.append(pattern)
            if found:
                lc = _line_count(models_file)
                flagged.append((str(models_file.relative_to(ROOT)), lc, found))

    flagged.sort(key=lambda x: x[1], reverse=True)

    report = [f"Model files with side-effect patterns: {len(flagged)}"]
    for path, lc, patterns in flagged[:15]:
        report.append(f"  {lc:>5} lines  {path}  [{', '.join(patterns)}]")

    print("\n".join(report))


# ── Metric: Models with transition methods + external side effects ───


def test_report_model_transition_side_effects():
    """Report model files that combine status transitions with external calls.

    Models that own state-machine logic (status field changes) AND also
    trigger external side effects (HTTP calls, Celery tasks, notifications)
    are the highest-risk coupling hotspots.
    """
    transition_keywords = [
        "status =",
        "self.status",
        ".save(",
        "transition",
        "mark_as_",
        "set_status",
        "activate",
        "deactivate",
        "complete",
        "cancel",
        "expire",
    ]
    external_keywords = [
        ".delay(",
        ".apply_async(",
        "send_mail",
        "send_email",
        "requests.post",
        "requests.get",
        "stripe.",
        "braintree.",
    ]

    flagged: list[tuple[str, int, list[str], list[str]]] = []

    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir():
            continue
        for models_file in app_dir.rglob("models.py"):
            if "/__pycache__/" in str(models_file):
                continue
            try:
                content = models_file.read_text()
            except Exception:
                continue
            transitions = [kw for kw in transition_keywords if kw in content]
            externals = [kw for kw in external_keywords if kw in content]
            if transitions and externals:
                lc = _line_count(models_file)
                flagged.append((str(models_file.relative_to(ROOT)), lc, transitions, externals))

    flagged.sort(key=lambda x: x[1], reverse=True)

    report = [f"Models with transition + external side effects: {len(flagged)}"]
    for path, lc, trans, ext in flagged[:15]:
        report.append(
            f"  {lc:>5} lines  {path}  "
            f"transitions=[{', '.join(trans[:3])}] externals=[{', '.join(ext[:3])}]"
        )

    print("\n".join(report))
