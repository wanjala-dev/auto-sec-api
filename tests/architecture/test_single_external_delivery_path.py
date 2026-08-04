"""Architecture guardrail: exactly ONE path sends messages outside the tenant.

ADR 0016 exists because a parallel Slack notifier grew up beside the notifications
funnel — no preference model, no delivery ledger, no retry, no dedup, and a per-event
shape that meant one scan raising 400 qualifying findings posted 400 messages. That
handler was retired and its job moved to the funnel's workspace-level external leg.

This test stops it happening a second time. Adding a new `@subscribes_to(...)` handler
that calls the delivery port directly is exactly how the first one appeared, and it
would silently reintroduce every property the leg provides.

**The rule.** Only two places may drive a `DeliveryChannelPort`:

* ``components/notifications/`` — the external leg, which owns what/when/how safely.
* ``components/integrations/`` — which owns the adapters themselves and the
  connect-time ``verify()`` probe.

Anything else wanting to notify a workspace dispatches through
``NotificationDispatcher.dispatch()`` and subscribes the connection to an event key.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.arch

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = ROOT / "components"

# Contexts legitimately allowed to touch the delivery seam.
_ALLOWED_CONTEXTS = {"notifications", "integrations"}

# Importing any of these means "I intend to send something out of the tenant".
_DELIVERY_SYMBOLS = {
    "DeliveryChannelPort",
    "get_delivery_channel_provider",
    "get_delivery_connection_repository",
    "deliver_external",
}

_DELIVERY_MODULES = (
    "components.integrations.application.ports.delivery_channel_port",
    "components.integrations.application.providers.delivery_channel_provider",
    "components.notifications.infrastructure.tasks.external_delivery_tasks",
)


def _context_of(path: Path) -> str:
    return path.relative_to(COMPONENTS_DIR).parts[0]


def _imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return found


def test_only_notifications_and_integrations_drive_external_delivery():
    violations: list[str] = []

    for path in COMPONENTS_DIR.rglob("*.py"):
        if "/tests/" in str(path):
            continue
        context = _context_of(path)
        if context in _ALLOWED_CONTEXTS:
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - unparseable file is another test's problem
            continue

        # ``ast.walk`` catches lazy in-function imports too — the first parallel
        # notifier would have passed a top-level-only check.
        imported = _imports(tree)
        for module in imported:
            if any(module.startswith(delivery) for delivery in _DELIVERY_MODULES) or (
                module.rsplit(".", 1)[-1] in _DELIVERY_SYMBOLS
            ):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert not violations, (
        "A second external-delivery path is being introduced — this is the exact "
        "regression ADR 0016 retired.\n"
        + "\n".join(sorted(violations))
        + "\n\nTo notify a workspace, dispatch through NotificationDispatcher.dispatch() "
        "and add an event key to the catalog; the external leg handles routing, noise "
        "control, redaction, the ledger, and retry."
    )


def test_the_retired_parallel_notifier_stays_retired():
    """Named explicitly so the regression is legible in a failure message."""
    retired = COMPONENTS_DIR / "integrations" / "application" / "handlers" / "finding_alert_delivery_handler.py"
    assert not retired.exists(), (
        "finding_alert_delivery_handler was retired by ADR 0016 — per-finding Slack "
        "delivery is now the notifications external leg, which digests scan batches "
        "into ONE message instead of one per finding."
    )
