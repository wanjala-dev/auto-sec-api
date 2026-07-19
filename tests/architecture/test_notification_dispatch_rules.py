"""Architecture guardrail: ALL notifications flow through the dispatcher funnel.

``NotificationDispatcher.dispatch()`` is the ONLY sanctioned way to create
``Notification`` rows from outside the notifications bounded context. It is
where preference filtering (user master toggle, per-workspace toggle, AI
channel toggles), deduplication, and — as of the notification-pipeline
consolidation — the delivery fan-out (realtime, web push, email) live.

Before this rule landed (2026-07-16), 9 call sites across 7 contexts bypassed
the funnel with raw ``Notification.objects.create(...)`` or direct
``create_notification`` imports. Those notifications ignored user preferences,
skipped dedup, and will silently miss every delivery channel added by the
unified-pipeline track. One site (document imports) had been failing with a
``TypeError`` on every run for months because the raw create drifted from the
model's fields — invisible precisely because it bypassed the funnel.

Cross-context access paths:
  * infrastructure / api layers → import ``NotificationDispatcher`` from
    ``components.notifications.infrastructure.adapters.notification_service``
  * application layers (use cases) → call
    ``get_notification_factory_provider().dispatch(...)``

Both accept ``allow_self_notify=True`` for system-generated events where the
recipient stands in as the actor.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# The notifications context owns the funnel — it may touch its own model and
# factory util freely.
ALLOWED_CONTEXT = "notifications"

NOTIFICATION_MODEL_MODULE = "infrastructure.persistence.notifications.models"

# Importing either of these outside components/notifications/ bypasses the
# preference filter (they wrap bare ``create_notification``):
BANNED_MODULE_IMPORTS = {
    "components.notifications.infrastructure.adapters.utils",
    "components.notifications.application.providers.notification_utils_provider",
}

BANNED_MANAGER_CALLS = {"create", "get_or_create", "update_or_create", "bulk_create"}


def _iter_context_files():
    for context_dir in sorted(COMPONENTS_DIR.iterdir()):
        if not context_dir.is_dir() or context_dir.name == ALLOWED_CONTEXT:
            continue
        for source_file in sorted(context_dir.rglob("*.py")):
            if "tests" in source_file.parts:
                continue
            yield source_file


def _notification_aliases(tree: ast.AST) -> set[str]:
    """Names the file binds to the Notification ORM model (asname-aware)."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == NOTIFICATION_MODEL_MODULE:
            for alias in node.names:
                if alias.name == "Notification":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _banned_module_imports(tree: ast.AST) -> list[str]:
    banned: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in BANNED_MODULE_IMPORTS:
            banned.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BANNED_MODULE_IMPORTS:
                    banned.append(alias.name)
    return banned


def _raw_manager_calls(tree: ast.AST, aliases: set[str]) -> list[int]:
    """Line numbers of ``Notification.objects.create(...)``-style calls."""
    if not aliases:
        return []
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in BANNED_MANAGER_CALLS):
            continue
        objects_attr = func.value
        if not (isinstance(objects_attr, ast.Attribute) and objects_attr.attr == "objects"):
            continue
        model_name = objects_attr.value
        if isinstance(model_name, ast.Name) and model_name.id in aliases:
            lines.append(node.lineno)
    return lines


def test_no_raw_notification_creates_outside_notifications_context():
    """Raw ``Notification.objects.create`` outside components/notifications is banned."""
    violations: list[str] = []
    for source_file in _iter_context_files():
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
        aliases = _notification_aliases(tree)
        for lineno in _raw_manager_calls(tree, aliases):
            violations.append(f"{source_file.relative_to(ROOT)}:{lineno}")
    assert not violations, (
        "Raw Notification manager writes bypass the dispatcher funnel "
        "(preferences, dedup, delivery fan-out). Use "
        "NotificationDispatcher().dispatch(...) — or "
        "get_notification_factory_provider().dispatch(...) from application "
        f"layers. Violations: {violations}"
    )


def test_no_direct_create_notification_imports_outside_notifications_context():
    """Importing the bare ``create_notification`` util outside the context is banned."""
    violations: list[str] = []
    for source_file in _iter_context_files():
        tree = ast.parse(source_file.read_text(), filename=str(source_file))
        for module in _banned_module_imports(tree):
            violations.append(f"{source_file.relative_to(ROOT)} imports {module}")
    assert not violations, (
        "Direct create_notification access bypasses preference filtering. "
        "Route through NotificationDispatcher().dispatch(...) or "
        "get_notification_factory_provider().dispatch(...). "
        f"Violations: {violations}"
    )
