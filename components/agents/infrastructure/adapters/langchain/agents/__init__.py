"""Auto-discovered agents subpackage (ADR 0003).

Drop a new agent module in this directory and `discover_agents()` will
import it at app startup, running its `@register_agent` decorator and
registering the class in the global `AgentRegistry`. No edits to
`base.py` or any other file are required.

Modules whose names start with an underscore (e.g. `_mixins`) are skipped
because they're library code, not agents.

`discover_agents()` is hooked into `components/agents/apps.py` via
`AppConfig.ready()` so it runs once at Django startup, after `base.py`
has finished loading. Calling it explicitly is also safe — it's
idempotent (the `_discovered` guard ensures it only walks the package
once per process).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

_discovered = False


def discover_agents() -> None:
    """Walk the `agents/` subpackage and import every public module so
    each agent's class-level `@register_agent` decorator runs.

    Idempotent: subsequent calls are no-ops.
    """
    global _discovered
    if _discovered:
        return
    for _, modname, _ in pkgutil.iter_modules(__path__):
        if modname.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{modname}")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to auto-discover agent module %s: %s", modname, exc
            )
    _discovered = True
